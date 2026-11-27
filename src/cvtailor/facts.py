"""Fact base (`facts.json`): schema, loading and consistency checks (DESIGN.md §7)."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from cvtailor.models import ParsedResume

FactType = Literal["achievement", "responsibility", "built", "scope", "leadership", "recognition"]
_NUMBER = re.compile(r"\d[\d.,]*[%+]?[KkMm]?")
_UNRESOLVED = re.compile(r"Conflict:|UNRESOLVED")
COVERABLE_KINDS = {"bullet", "intro"}


class FactsError(ValueError):
    pass


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class Role(_Model):
    id: str
    employer: str
    title: str
    start: str | None = None
    end: str | None = None
    is_current: bool = False


class Metric(_Model):
    value: str
    meaning: str
    period: str | None = None
    source: str | None = None


class UsedIn(_Model):
    resume_id: str
    quote: str


class Fact(_Model):
    id: str
    role_id: str
    type: FactType
    claim: str
    metrics: list[Metric]
    skills: list[str]
    tags: list[str]
    used_in: list[UsedIn]
    sources: list[str]
    confidence: Literal["stated", "inferred"]
    verified: bool
    notes: str = ""


class Skill(_Model):
    name: str
    aliases: list[str] = []
    category: str = ""
    recency: Literal["current", "previous"] = "current"
    evidence: list[str] = []
    basic: bool = False


class FactsFile(_Model):
    schema_version: int
    roles: list[Role]
    facts: list[Fact]
    skills: list[Skill]


class FactsReport(BaseModel):
    problems: list[str]
    warnings: list[str]
    stats: dict[str, int]


def load_facts(source: Path | str | dict) -> FactsFile:
    data = source if isinstance(source, dict) else json.loads(Path(source).read_text())
    try:
        return FactsFile.model_validate(data)
    except ValidationError as exc:
        lines = []
        for err in exc.errors()[:10]:
            loc = list(err["loc"])
            if len(loc) >= 2 and loc[0] == "facts" and isinstance(loc[1], int):
                fid = data["facts"][loc[1]].get("id", f"#{loc[1]}")
                loc = [fid] + loc[2:]
            lines.append(f"{'.'.join(map(str, loc))}: {err['msg']}")
        raise FactsError("facts.json does not match the schema:\n  " + "\n  ".join(lines)) from None


def numbers_in(text: str) -> list[str]:
    """Digit-bearing tokens as written (`42%`, `2.5M`, `120+`, `350K`)."""
    return [m.group().rstrip(".,") for m in _NUMBER.finditer(text)]


def _metric_text(facts: list[Fact]) -> str:
    return " | ".join(m.value for f in facts for m in f.metrics)


def check_facts(facts: FactsFile, resumes: dict[str, ParsedResume] | None, partial: bool = False) -> FactsReport:
    """`partial=True`: `resumes` is a subset; used_in entries for other resumes are not checked."""
    problems: list[str] = []
    warnings: list[str] = []
    ids = [f.id for f in facts.facts]
    id_set = set(ids)
    roles = {r.id for r in facts.roles}
    skill_names = {s.name for s in facts.skills} | {a for s in facts.skills for a in s.aliases}

    for fid, n in Counter(ids).items():
        if n > 1:
            problems.append(f"{fid}: duplicate fact id ({n} times)")
    for f in facts.facts:
        if f.role_id not in roles:
            problems.append(f"{f.id}: unknown role {f.role_id}")
        for s in f.skills:
            if s not in skill_names:
                problems.append(f"{f.id}: skill {s!r} is not in skills[]")
        values = _metric_text([f])
        for tok in numbers_in(f.claim):
            if tok not in values:
                problems.append(f"{f.id}: number {tok!r} in claim is not in metrics")
        if _UNRESOLVED.search(f.notes):
            problems.append(f"{f.id}: unresolved note: {f.notes[:60]!r}")
    for s in facts.skills:
        for e in s.evidence:
            if e not in id_set:
                problems.append(f"skill {s.name!r}: evidence {e} is not a fact id")
        if not s.evidence and not s.basic:
            problems.append(f"skill {s.name!r}: no evidence (mark everyday tools with basic: true)")

    unverified = [f.id for f in facts.facts if not f.verified]
    if unverified:
        warnings.append(f"{len(unverified)} facts not verified (not used for edits): {', '.join(unverified[:20])}")

    if resumes is not None:
        _check_against_resumes(facts, resumes, problems, warnings, partial)

    stats = {"facts": len(facts.facts), "verified": len(facts.facts) - len(unverified),
             "roles": len(facts.roles), "skills": len(facts.skills)}
    return FactsReport(problems=problems, warnings=warnings, stats=stats)


def _check_against_resumes(
    facts: FactsFile, resumes: dict[str, ParsedResume], problems: list[str], warnings: list[str], partial: bool = False
) -> None:
    covering: dict[tuple[str, str], list[Fact]] = {}
    for f in facts.facts:
        for u in f.used_in:
            resume = resumes.get(u.resume_id)
            if resume is None and partial:
                continue
            if resume is None:
                problems.append(f"{f.id}: used_in refers to unknown resume {u.resume_id!r}")
                continue
            hits = [b for b in resume.blocks if u.quote in b.text]
            if not hits:
                problems.append(f"{f.id}: quote not found in {u.resume_id}: {u.quote[:60]!r}")
            for b in hits:
                covering.setdefault((u.resume_id, b.id), []).append(f)

    for rid, resume in resumes.items():
        for b in resume.blocks:
            fs = covering.get((rid, b.id))
            if fs is None:
                if b.editable and b.kind in COVERABLE_KINDS:
                    warnings.append(f"{rid}/{b.id}: editable block not covered by any fact: {b.text[:50]!r}")
                continue
            values = _metric_text(fs)
            for tok in numbers_in(b.text):
                if tok not in values:
                    problems.append(
                        f"{rid}/{b.id}: number {tok!r} not in metrics of covering facts {[f.id for f in fs]}"
                    )


# --- indexes used by AI steps and validators (M3) -------------------------------

class RoleMapError(ValueError):
    pass


def verified_facts(facts: FactsFile) -> dict[str, Fact]:
    return {f.id: f for f in facts.facts if f.verified}


def coverage(facts: FactsFile, resume_id: str, resume: ParsedResume) -> dict[str, list[str]]:
    """fact id -> bullet/intro blocks of this resume that already state it (verified facts only)."""
    blocks = [b for b in resume.blocks if b.kind in COVERABLE_KINDS]
    out: dict[str, list[str]] = {}
    for f in verified_facts(facts).values():
        hits = [b.id for u in f.used_in if u.resume_id == resume_id for b in blocks if u.quote in b.text]
        if hits:
            out[f.id] = sorted(set(hits), key=hits.index)
    return out


def groups(facts: FactsFile) -> list[list[str]]:
    """Verified facts that share a used_in quote are usually told as one bullet."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_quote: dict[tuple[str, str], list[str]] = {}
    for f in verified_facts(facts).values():
        for u in f.used_in:
            by_quote.setdefault((u.resume_id, u.quote), []).append(f.id)
    for ids in by_quote.values():
        for other in ids[1:]:
            parent[find(other)] = find(ids[0])
    comps: dict[str, set[str]] = {}
    for ids in by_quote.values():
        for i in ids:
            comps.setdefault(find(i), set()).add(i)
    return sorted((sorted(c) for c in comps.values() if len(c) > 1), key=lambda c: c[0])


def _tokens(s: str) -> list[str]:
    from cvtailor.naming import slug
    return slug(s).split("-")


def _prefix_match(a: list[str], b: list[str]) -> bool:
    n = min(len(a), len(b))
    return n > 0 and a[:n] == b[:n]


def role_map(facts: FactsFile, resume: ParsedResume, overrides: dict[str, str]) -> dict[tuple[str, str], str]:
    """(company slug, role slug) of editable blocks -> facts role_id.

    A role of an older company (priority >= 2) with no facts role is left out instead of failing;
    the caller makes its blocks read-only."""
    role_ids = {r.id for r in facts.roles}
    prio = {(b.company, b.role): b.priority or 1 for b in resume.blocks
            if b.editable and b.kind in COVERABLE_KINDS and b.company and b.role}
    pairs = sorted(prio)
    out: dict[tuple[str, str], str] = {}
    errors: list[str] = []
    for company, role in pairs:
        key = f"{company}/{role}"
        if key in overrides:
            if overrides[key] not in role_ids:
                errors.append(f"{key}: override points to unknown role {overrides[key]!r}")
            else:
                out[(company, role)] = overrides[key]
            continue
        ct, rt = company.split("-"), role.split("-")
        same_company = [
            r for r in facts.roles
            if _prefix_match(ct, _tokens(r.employer)) or _prefix_match(ct, _tokens(r.employer.split("/")[0]))
        ]
        exact = [r for r in same_company if _tokens(r.title) == rt]
        cands = exact or [r for r in same_company if _prefix_match(rt, _tokens(r.title))]
        if len(cands) == 1:
            out[(company, role)] = cands[0].id
        elif not cands and prio[(company, role)] >= 2:
            continue
        else:
            found = ", ".join(r.id for r in cands) or "none"
            errors.append(f"{key}: {'ambiguous' if cands else 'no'} matching facts role (candidates: {found})")
    if errors:
        raise RoleMapError(
            "cannot map resume roles to facts.json roles; add role_map entries to resumes.yaml:\n  "
            + "\n  ".join(errors)
        )
    return out


def normalize_skills(names: list[str], facts: FactsFile) -> list[str]:
    canon = {}
    for s in facts.skills:
        for n in [s.name, *s.aliases]:
            canon.setdefault(n.casefold(), s.name)
    return [canon.get(n.casefold(), n) for n in names]
