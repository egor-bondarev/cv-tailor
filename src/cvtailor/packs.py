"""Inputs for AI steps (`<step>.pack.md`). Only verified facts ever appear here."""

from __future__ import annotations

import json

from cvtailor.checks import CheckError
from cvtailor.config import ResumeConfig
from cvtailor.facts import groups
from cvtailor.models import Op
from cvtailor.schemas import Analysis, Vacancy
from cvtailor.validate import BULLET_KINDS, PlanContext, max_chars


def _json(obj) -> str:
    return "```json\n" + json.dumps(obj, ensure_ascii=False, indent=2) + "\n```"


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
    facts = [_fact(f) for f in ctx.verified.values()]
    return (
        f"# Vacancy\n\n{_json(vacancy.model_dump())}\n\n"
        f"# Editable resume blocks\n\n{_json(editable)}\n\n"
        f"# Read-only resume context\n\n{_json(context)}\n\n"
        f"# Verified facts\n\n{_json(facts)}\n\n"
        f"# groups (facts usually told as one bullet)\n\n{_json(groups(ctx.facts))}\n\n"
        f"# covered_by (fact -> blocks that already state it)\n\n{_json(ctx.covered)}\n"
    )


def tailor_pack(vacancy: Vacancy, analysis: Analysis, ctx: PlanContext, errors: list[CheckError]) -> str:
    verified = ctx.verified
    cands = [fid for fid in analysis.candidate_facts if fid in verified]
    cset = set(cands)
    grp = [[i for i in g if i in cset] for g in groups(ctx.facts)]
    grp = [g for g in grp if len(g) > 1]
    skills = [{"name": s.name, "aliases": s.aliases, "basic": s.basic, "recency": s.recency,
               "has_verified_evidence": any(e in verified for e in s.evidence)} for s in ctx.facts.skills]
    editable, context = _blocks(ctx, with_limits=True)
    parts = [
        f"# Vacancy\n\n{_json(vacancy.model_dump())}",
        f"# Analysis\n\n{_json(analysis.model_copy(update={'candidate_facts': cands}).model_dump())}",
        f"# Editable resume blocks\n\n{_json(editable)}",
        f"# Read-only resume context\n\n{_json(context)}",
        f"# Candidate facts (verified)\n\n{_json([_fact(verified[i], full=True) for i in cands])}",
        f"# groups within candidates\n\n{_json(grp)}",
        f"# covered_by\n\n{_json({k: v for k, v in ctx.covered.items() if k in cset})}",
        f"# Skills vocabulary\n\n{_json(skills)}",
        f"# Limits\n\n{_json(ctx.limits.model_dump())}",
        "# Length budget\n\nSum of all editable blocks after your edits (replaced texts, minus deleted bullets, plus new bullets) "
        "must not exceed `editable_total_max`.\n\n" + _json(_budget(ctx)),
    ]
    if errors:
        parts.append("# Errors from previous attempt\n\nFix every error below; keep the operations that were fine.\n\n"
                     + _json([e.model_dump() for e in errors]))
    return "\n\n".join(parts) + "\n"


def _budget(ctx: PlanContext) -> dict:
    total = sum(len(b.text) for b in ctx.resume.blocks if b.editable)
    return {"editable_total_chars": total, "editable_total_max": int(ctx.limits.total_editable_max_ratio * total),
            "summary_min_chars": int(ctx.limits.summary_min_ratio * next((len(b.text) for b in ctx.resume.blocks if b.kind == "summary"), 0))}


def review_pack(ops: list[Op], ctx: PlanContext) -> str:
    verified = ctx.verified
    items = []
    for op in ops:
        b = ctx.resume.get(op.target)
        items.append({
            "op": op.id, "kind": op.op, "block": b.id,
            "before": b.text if op.op != "insert_after" else None,
            "anchor": b.text if op.op == "insert_after" else None,
            "after": op.new_text if op.op in ("replace", "insert_after") else op.new_value,
            "evidence": [_fact(verified[f], full=True) for f in op.evidence if f in verified],
            "reason": op.reason,
        })
    return f"# Edits to review\n\n{_json(items)}\n"
