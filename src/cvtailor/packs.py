"""Inputs for AI steps (`<step>.pack.md`). Only verified facts ever appear here."""

from __future__ import annotations

import json

from cvtailor.checks import CheckError
from cvtailor.config import ResumeConfig
from cvtailor.facts import groups
from cvtailor.models import Op
from cvtailor.schemas import Analysis, Vacancy
from cvtailor.validate import BULLET_KINDS, PlanContext, max_chars, split_skill_items


def _compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _json(obj) -> str:
    """Compact JSON; a list puts one item per line so it stays readable."""
    if isinstance(obj, list) and obj:
        body = "[\n" + ",\n".join(_compact(x) for x in obj) + "\n]"
    elif isinstance(obj, dict) and obj:
        body = "{\n" + ",\n".join(f"{_compact(k)}:{_compact(v)}" for k, v in obj.items()) + "\n}"
    else:
        body = _compact(obj)
    return "```json\n" + body + "\n```"


def _fact_line(f) -> str:
    metrics = "; ".join(m.value for m in f.metrics)
    line = f"{f.id} | {f.type} | {f.claim}"
    if metrics:
        line += f" | metrics: {metrics}"
    if f.notes:
        line += f" | note: {f.notes}"
    return line


def _covered_editable(ctx: PlanContext, only: set[str] | None = None) -> dict:
    editable = {b.id for b in ctx.resume.blocks if b.editable}
    out = {}
    for fid, blocks in ctx.covered.items():
        if only is not None and fid not in only:
            continue
        kept = [b for b in blocks if b in editable]
        if kept:
            out[fid] = kept
    return out


def _skills_lines(ctx: PlanContext) -> str:
    verified = ctx.verified
    by_cat: dict[str, list[str]] = {}
    for s in ctx.facts.skills:
        marks = []
        if any(e in verified for e in s.evidence):
            marks.append("ev")
        if s.basic:
            marks.append("basic")
        if s.recency == "previous":
            marks.append("prev")
        by_cat.setdefault(s.category or "Other", []).append(s.name + (f" [{', '.join(marks)}]" if marks else ""))
    return "\n".join(f"{cat}: {', '.join(items)}" for cat, items in by_cat.items())


def _fact(f, full: bool = False) -> dict:
    d = {"id": f.id, "role_id": f.role_id, "type": f.type, "claim": f.claim,
         "metrics": [m.value for m in f.metrics]}
    if full:
        d.update(skills=f.skills, notes=f.notes)
    elif f.notes:
        d["notes"] = f.notes
    return d


def _blocks(ctx: PlanContext, with_limits: bool = False) -> tuple[list[dict], list[dict]]:
    editable, context = [], []
    for b in ctx.resume.blocks:
        if b.editable:
            item = {"id": b.id, "kind": b.kind, "text": b.text}
            if b.kind in BULLET_KINDS:
                item["role"] = f"{b.company}/{b.role}"
                item["priority"] = b.priority or 1
            if with_limits:
                item["chars"] = len(b.text)
                item["max_chars"] = max_chars(b, ctx.limits)
            editable.append(item)
        elif b.id.startswith(("h.", "exp.", "early.")):
            context.append({"id": b.id, "text": b.text})
    return editable, context


def extract_pack(vacancy_text: str) -> str:
    return "# Vacancy text\n\n" + vacancy_text.strip() + "\n"


def route_pack(vacancy: Vacancy, resumes: list[tuple[ResumeConfig, str]]) -> str:
    items = [{"id": r.id, "label": r.label, "target_role": r.target_role, "summary": summary} for r, summary in resumes]
    return f"# Vacancy\n\n{_json(vacancy.model_dump())}\n\n# Base resumes\n\n{_json(items)}\n"


def analyze_pack(vacancy: Vacancy, ctx: PlanContext) -> str:
    editable, context = _blocks(ctx)
    by_role: dict[str, list[str]] = {}
    for f in ctx.verified.values():
        by_role.setdefault(f.role_id, []).append(_fact_line(f))
    facts = "\n\n".join(f"## {role}\n" + "\n".join(lines) for role, lines in by_role.items())
    return (
        f"# Vacancy\n\n{_json(vacancy.model_dump())}\n\n"
        f"# Editable resume blocks\n\n{_json(editable)}\n\n"
        f"# Read-only resume context\n\n{_json(context)}\n\n"
        "# Verified facts\n\nGrouped by `## role_id`; one per line: `id | type | claim | metrics | note`.\n\n"
        f"{facts}\n\n"
        f"# groups (facts usually told as one bullet)\n\n{_json(groups(ctx.facts))}\n\n"
        f"# covered_by (fact -> editable blocks that already state it)\n\n{_json(_covered_editable(ctx))}\n"
    )


def tailor_pack(vacancy: Vacancy, analysis: Analysis, ctx: PlanContext, errors: list[CheckError]) -> str:
    verified = ctx.verified
    cands = [fid for fid in analysis.candidate_facts if fid in verified]
    cset = set(cands)
    grp = [[i for i in g if i in cset] for g in groups(ctx.facts)]
    grp = [g for g in grp if len(g) > 1]
    editable, context = _blocks(ctx, with_limits=True)
    slim = analysis.model_copy(update={"candidate_facts": cands}).model_dump()
    for r in slim["relevance"]:
        r.pop("reason", None)
    parts = []
    if errors:
        parts.append("# Errors from previous attempt\n\nFix every error below; keep the operations that were fine. "
                     "The rest of this input is unchanged from the previous attempt.\n\n"
                     + _json([e.model_dump() for e in errors]))
    parts += [
        f"# Vacancy\n\n{_json(vacancy.model_dump())}",
        f"# Analysis\n\n{_json(slim)}",
        f"# Editable resume blocks\n\n{_json(editable)}",
        f"# Read-only resume context\n\n{_json(context)}",
        f"# Candidate facts (verified)\n\n{_json([_fact(verified[i], full=True) for i in cands])}",
        f"# groups within candidates\n\n{_json(grp)}",
        f"# covered_by\n\n{_json(_covered_editable(ctx, cset))}",
        "# Skills vocabulary\n\nOne line per category. Marks: `ev` has verified evidence, `basic` everyday tool, "
        "`prev` previous experience only. A new skills item needs `ev` or `basic`.\n\n" + _skills_lines(ctx),
        f"# Limits\n\n{_json(ctx.limits.model_dump())}",
        "# Length budget\n\nSum of all editable blocks after your edits (replaced texts, minus deleted bullets, plus new bullets) "
        "must not exceed `editable_total_max`.\n\n" + _json(_budget(ctx)),
    ]
    return "\n\n".join(parts) + "\n"


def _budget(ctx: PlanContext) -> dict:
    total = sum(len(b.text) for b in ctx.resume.blocks if b.editable)
    return {"editable_total_chars": total, "editable_total_max": int(ctx.limits.total_editable_max_ratio * total),
            "summary_min_chars": int(ctx.limits.summary_min_ratio * next((len(b.text) for b in ctx.resume.blocks if b.kind == "summary"), 0))}


def _new_skill_backing(orig_value: str, new_value: str, ctx: PlanContext) -> list[dict]:
    """For each skills item that is new in the line: whether it is basic or which verified facts back it."""
    verified = ctx.verified
    existing = {i.casefold() for i, _ in split_skill_items(orig_value)}
    index = {n.casefold(): s for s in ctx.facts.skills for n in (s.name, *s.aliases)}
    out = []
    for item, previous in split_skill_items(new_value):
        if item.casefold() in existing:
            continue
        skill = index.get(item.casefold())
        entry = {"item": item, "previous_experience": previous}
        if skill is not None:
            entry["basic"] = skill.basic
            entry["evidence"] = [_fact(verified[e]) for e in skill.evidence if e in verified]
        out.append(entry)
    return out


def review_pack(ops: list[Op], ctx: PlanContext) -> str:
    verified = ctx.verified
    items = []
    for op in ops:
        b = ctx.resume.get(op.target)
        items.append({
            "op": op.id, "kind": op.op, "block": b.id,
            "before": b.text if op.op != "insert_after" else None,
            "anchor": b.text if op.op == "insert_after" else None,
            "after": op.new_text if op.op in ("replace", "insert_after")
            else b.text[: b.text.index(": ") + 2] + op.new_value if op.op == "replace_skills" else None,
            "evidence": [_fact(verified[f], full=True) for f in op.evidence if f in verified],
            "reason": op.reason,
        })
        if op.op == "replace_skills":
            items[-1]["new_items"] = _new_skill_backing(b.text[b.text.index(": ") + 2:], op.new_value, ctx)
    return f"# Edits to review\n\n{_json(items)}\n"
