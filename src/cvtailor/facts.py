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


def check_facts(facts: FactsFile, resumes: dict[str, ParsedResume] | None) -> FactsReport:
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
        _check_against_resumes(facts, resumes, problems, warnings)

    stats = {"facts": len(facts.facts), "verified": len(facts.facts) - len(unverified),
             "roles": len(facts.roles), "skills": len(facts.skills)}
    return FactsReport(problems=problems, warnings=warnings, stats=stats)


def _check_against_resumes(
    facts: FactsFile, resumes: dict[str, ParsedResume], problems: list[str], warnings: list[str]
) -> None:
    covering: dict[tuple[str, str], list[Fact]] = {}
    for f in facts.facts:
        for u in f.used_in:
            resume = resumes.get(u.resume_id)
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
