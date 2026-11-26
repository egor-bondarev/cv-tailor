"""Plan validators (DESIGN.md §8, rules 1-9) and greedy selection of a valid subset."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from cvtailor.checks import CheckError
from cvtailor.config import Limits
from cvtailor.facts import Fact, FactsFile, coverage, role_map, verified_facts
from cvtailor.models import Block, BuildError, Op, ParsedResume
from cvtailor.numbers import metric_tokens, number_tokens, protected_names
from cvtailor.requests import check_ops

BULLET_KINDS = {"bullet", "intro"}
_PREVIOUS = "previous experience with"


class PlanContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    resume: ParsedResume
    facts: FactsFile
    resume_id: str
    limits: Limits
    roles: dict[tuple[str, str], str]
    covered: dict[str, list[str]]
    protected: list[str]

    @property
    def verified(self) -> dict[str, Fact]:
        return verified_facts(self.facts)


def make_context(resume: ParsedResume, facts: FactsFile, resume_id: str, limits: Limits,
                 overrides: dict[str, str]) -> PlanContext:
    skill_names = [n for s in facts.skills for n in (s.name, *s.aliases)]
    texts = [b.text for b in resume.blocks]
    return PlanContext(
        resume=resume, facts=facts, resume_id=resume_id, limits=limits,
        roles=role_map(facts, resume, overrides),
        covered=coverage(facts, resume_id, resume),
        protected=protected_names(skill_names, texts),
    )


# --- skills line parsing -----------------------------------------------------------

def _split_top(text: str, seps: tuple[str, ...]) -> list[str]:
    parts, depth, cur, i = [], 0, "", 0
    while i < len(text):
        ch = text[i]
        depth += ch == "("
        depth -= ch == ")"
        hit = next((s for s in seps if depth == 0 and text.startswith(s, i)), None)
        if hit:
            parts.append(cur)
            cur, i = "", i + len(hit)
            continue
        cur += ch
        i += 1
    parts.append(cur)
    return parts


def _clean(item: str) -> str:
    item = item.strip().rstrip(".").strip()
    return item[4:].strip() if item.lower().startswith("and ") else item


def split_skill_items(value: str) -> list[tuple[str, bool]]:
    """Skill items of a skills-line value with a `previous experience` flag; parentheses become sub-items."""
    out: list[tuple[str, bool]] = []
    for seg in _split_top(value, (";",)):
        seg = seg.strip()
        previous = seg.lower().startswith(_PREVIOUS)
        if previous:
            seg = seg[len(_PREVIOUS):]
        for raw in _split_top(seg, (",", " and ")):
            item = _clean(raw)
            if not item:
                continue
            if "(" in item and item.endswith(")"):
                head, inner = item[: item.index("(")], item[item.index("(") + 1 : -1]
                if _clean(head):
                    out.append((_clean(head), previous))
                out += [(_clean(x), previous) for x in inner.split(",") if _clean(x)]
            else:
                out.append((item, previous))
    return out


# --- validators -------------------------------------------------------------------------

def _block(ctx: PlanContext, op: Op) -> Block:
    return ctx.resume.get(op.target)


def _new_len(block: Block, op: Op) -> int:
    if op.op == "replace":
        return len(op.new_text)
    if op.op == "replace_skills":
        return len(block.text[: block.text.index(": ") + 2]) + len(op.new_value)
    return 0


def max_chars(b: Block, lim: Limits) -> int | None:
    """Longest allowed new text for a replace of block `b` (whole paragraph; skills: whole line)."""
    n = len(b.text)
    return {
        "bullet": min(lim.bullet_max_chars, int(lim.bullet_replace_max_ratio * n)),
        "intro": int(lim.intro_max_ratio * n),
        "summary": int(lim.summary_max_ratio * n),
        "title": lim.title_max_chars,
        "skills": int(lim.skills_line_max_ratio * n),
    }.get(b.kind)


def _check_lengths(op: Op, b: Block, lim: Limits) -> list[str]:
    out = []
    if op.op == "insert_after":
        if len(op.new_text) > lim.bullet_max_chars:
            out.append(f"new bullet has {len(op.new_text)} chars, limit {lim.bullet_max_chars}")
        return out
    n, orig = _new_len(b, op), len(b.text)
    if op.op == "replace_skills":
        if n > lim.skills_line_max_ratio * orig:
            out.append(f"skills line {n} chars > {lim.skills_line_max_ratio:.0%} of {orig}")
    elif b.kind == "bullet":
        if n > lim.bullet_max_chars or n > lim.bullet_replace_max_ratio * orig:
            out.append(f"bullet {n} chars, limits {lim.bullet_max_chars} and {lim.bullet_replace_max_ratio:.0%} of {orig}")
    elif b.kind == "intro" and n > lim.intro_max_ratio * orig:
        out.append(f"intro {n} chars > {lim.intro_max_ratio:.0%} of {orig}")
    elif b.kind == "summary" and not (lim.summary_min_ratio * orig <= n <= lim.summary_max_ratio * orig):
        out.append(f"summary {n} chars outside {lim.summary_min_ratio:.0%}-{lim.summary_max_ratio:.0%} of {orig}")
    elif b.kind == "title" and n > lim.title_max_chars:
        out.append(f"title {n} chars > {lim.title_max_chars}")
    return out


def _check_skills(op: Op, b: Block, ctx: PlanContext) -> list[str]:
    orig_value = b.text[b.text.index(": ") + 2:]
    existing = {i.casefold() for i, _ in split_skill_items(orig_value)}
    index = {n.casefold(): s for s in ctx.facts.skills for n in (s.name, *s.aliases)}
    verified = ctx.verified
    out = []
    for item, previous in split_skill_items(op.new_value):
        if item.casefold() in existing:
            continue
        skill = index.get(item.casefold())
        if skill is None:
            out.append(f"{item!r} is not in facts.json skills")
        elif not skill.basic and not any(e in verified for e in skill.evidence):
            out.append(f"{item!r} has no verified evidence (and is not basic)")
        elif skill.recency == "previous" and not previous:
            out.append(f"{item!r} is a previous skill; put it after '{_PREVIOUS}'")
    return out


def _per_op(op: Op, ctx: PlanContext) -> list[CheckError]:
    errs: list[CheckError] = []

    def err(rule: str, detail: str) -> None:
        errs.append(CheckError(rule=rule, detail=detail, op=op.id))

    try:
        check_ops(ctx.resume, [op])
    except BuildError as exc:
        err("target", str(exc))
        return errs
    b = _block(ctx, op)
    verified = ctx.verified
    all_ids = {f.id for f in ctx.facts.facts}
    for fid in op.evidence:
        if fid not in all_ids:
            err("evidence", f"unknown fact {fid}")
        elif fid not in verified:
            err("evidence", f"fact {fid} is not verified")
    ev = [verified[f] for f in op.evidence if f in verified]
    if op.op in ("replace", "insert_after") and b.kind in BULLET_KINDS | {"title", "summary"} and not op.evidence:
        err("evidence", f"{op.op} of {b.kind} {b.id} needs evidence")
    if b.kind in BULLET_KINDS and b.company and b.role and op.op != "delete":
        role_id = ctx.roles.get((b.company, b.role))
        if role_id is None:
            err("role", f"no facts role mapped for {b.company}/{b.role}")
        for f in ev:
            if role_id and f.role_id != role_id:
                err("role", f"fact {f.id} belongs to {f.role_id}, block {b.id} is {role_id}")
    if op.op in ("replace", "insert_after"):
        allowed = metric_tokens([m.value for f in ev for m in f.metrics])
        if op.op == "replace":
            allowed |= set(number_tokens(b.text, ctx.protected))
        for tok in number_tokens(op.new_text, ctx.protected):
            if tok not in allowed:
                err("numbers", f"number {tok!r} is not a metric of evidence {op.evidence or '[]'}")
    if op.op == "replace_skills":
        for d in _check_skills(op, b, ctx):
            err("skills", d)
    for d in _check_lengths(op, b, ctx.limits):
        err("length", d)
    return errs


def _plan_level(ops: list[Op], ctx: PlanContext) -> list[CheckError]:
    errs: list[CheckError] = []
    lim, resume = ctx.limits, ctx.resume
    try:
        check_ops(resume, ops)
    except BuildError as exc:
        errs.append(CheckError(rule="combination", detail=str(exc)))
    if len(ops) > lim.max_ops_per_plan:
        errs.append(CheckError(rule="structure", detail=f"{len(ops)} ops > limit {lim.max_ops_per_plan}"))
    by_target = {op.target: op for op in ops if op.op != "insert_after"}
    roles: dict[tuple, int] = {}
    for b in resume.blocks:
        if b.kind == "bullet" and b.editable and not b.nesting:
            roles[(b.company, b.role)] = roles.get((b.company, b.role), 0) + 1
    after = dict(roles)
    for op in ops:
        b = resume.get(op.target)
        if op.op == "delete":
            after[(b.company, b.role)] -= 1
        elif op.op == "insert_after":
            after[(b.company, b.role)] = after.get((b.company, b.role), 0) + 1
    for key, n in after.items():
        if n > max(lim.max_bullets_per_role, roles.get(key, 0)):
            errs.append(CheckError(rule="structure", detail=f"{key[0]}/{key[1]} would have {n} bullets"))
    editable = [b for b in resume.blocks if b.editable]
    orig_total = sum(len(b.text) for b in editable)
    new_total = sum(_new_len(b, by_target[b.id]) if b.id in by_target else len(b.text) for b in editable)
    new_total += sum(len(op.new_text) for op in ops if op.op == "insert_after")
    budget = int(lim.total_editable_max_ratio * orig_total)
    if orig_total and new_total > budget:
        errs.append(CheckError(rule="structure", detail=(
            f"editable text would be {new_total} chars, budget {budget} ({new_total - budget} chars over); "
            "shorten texts or drop an edit")))
    return errs


def _duplicates(ops: list[Op], ctx: PlanContext) -> list[CheckError]:
    errs: list[CheckError] = []
    changed = {op.target for op in ops if op.op in ("replace", "replace_skills", "delete")}
    used: dict[str, int] = {}
    for op in sorted(ops, key=lambda o: o.id):
        b = ctx.resume.get(op.target)
        if not (op.op == "insert_after" or (op.op == "replace" and b.kind in BULLET_KINDS)):
            continue
        own = op.target if op.op == "replace" else None
        for fid in op.evidence:
            stays = [bid for bid in ctx.covered.get(fid, []) if bid not in changed and bid != own]
            if stays:
                errs.append(CheckError(rule="duplicate_fact", op=op.id,
                                       detail=f"fact {fid} is already stated in unchanged {stays[0]}"))
            if fid in used:
                errs.append(CheckError(rule="duplicate_fact", op=op.id,
                                       detail=f"fact {fid} is already used by op {used[fid]}"))
            used.setdefault(fid, op.id)
    return errs


def validate_ops(ops: list[Op], ctx: PlanContext) -> list[CheckError]:
    errs = [e for op in ops for e in _per_op(op, ctx)]
    if any(e.rule == "target" for e in errs):
        return errs
    return errs + _plan_level(ops, ctx) + _duplicates(ops, ctx)


def split_valid(ops: list[Op], ctx: PlanContext) -> tuple[list[Op], list[tuple[Op, list[CheckError]]]]:
    kept: list[Op] = []
    dropped: list[tuple[Op, list[CheckError]]] = []
    for op in sorted(ops, key=lambda o: o.id):
        errs = [e for e in validate_ops(kept + [op], ctx) if e.op in (op.id, None)]
        if errs:
            dropped.append((op, errs))
        else:
            kept.append(op)
    return kept, dropped
