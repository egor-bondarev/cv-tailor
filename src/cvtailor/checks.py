"""Parse AI JSON output and check it against the resume and facts (DESIGN.md §6)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from cvtailor.facts import FactsFile, normalize_skills, verified_facts
from cvtailor.models import Op, ParsedResume
from cvtailor.schemas import AiOp, AiPlan, Analysis, Route, Vacancy

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"```(?:json)?\s*\n?|```")
RELEVANCE_KINDS = {"bullet", "intro"}


class CheckError(BaseModel):
    rule: str
    detail: str
    op: int | None = None


def _top_level_objects(text: str) -> list[object]:
    decoder = json.JSONDecoder()
    found, i = [], 0
    while True:
        start = text.find("{", i)
        if start < 0:
            return found
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            i = start + 1
            continue
        found.append(obj)
        i = end


def _errors(exc: ValidationError) -> list[CheckError]:
    return [CheckError(rule="schema", detail=f"{'.'.join(map(str, e['loc'])) or '<root>'}: {e['msg']}")
            for e in exc.errors()[:10]]


def parse_json_text(text: str, model: type[T]) -> tuple[T | None, list[CheckError]]:
    """Last top-level JSON object in `text` that matches `model` (fences stripped, nested objects skipped)."""
    candidates = _top_level_objects(_FENCE.sub("\n", text))
    last_errors = [CheckError(rule="schema", detail="no JSON object found")]
    for obj in reversed(candidates):
        try:
            return model.model_validate(obj), []
        except ValidationError as exc:
            if obj is candidates[-1]:
                last_errors = _errors(exc)
    return None, last_errors


def load_ai_json(path: Path, model: type[T]) -> tuple[T | None, list[CheckError]]:
    if not path.exists():
        return None, [CheckError(rule="missing", detail=f"{path.name} was not written")]
    text = path.read_text()
    if not text.strip():
        return None, [CheckError(rule="empty", detail=f"{path.name} is empty")]
    return parse_json_text(text, model)


def check_vacancy(v: Vacancy, facts: FactsFile) -> tuple[Vacancy, list[CheckError]]:
    return v.model_copy(update={"skills": normalize_skills(v.skills, facts)}), []


def check_route(r: Route, resume_ids: list[str]) -> list[CheckError]:
    errs = []
    for rid in {r.choice, *r.ranking} - set(resume_ids):
        errs.append(CheckError(rule="route", detail=f"unknown resume id {rid!r}; use one of {resume_ids}"))
    if not r.ranking or r.ranking[0] != r.choice:
        errs.append(CheckError(rule="route", detail="ranking must start with choice"))
    if len(resume_ids) >= 2 and len(set(r.ranking)) < 2:
        errs.append(CheckError(rule="route", detail="ranking must list at least two resumes"))
    return errs


def check_analysis(a: Analysis, resume: ParsedResume, facts: FactsFile) -> list[CheckError]:
    errs: list[CheckError] = []
    verified = verified_facts(facts)
    all_ids = {f.id for f in facts.facts}
    block_ids = {b.id for b in resume.blocks}

    def fact_ok(fid: str, where: str) -> None:
        if fid not in all_ids:
            errs.append(CheckError(rule="fact", detail=f"{where}: unknown fact {fid}"))
        elif fid not in verified:
            errs.append(CheckError(rule="fact", detail=f"{where}: fact {fid} is not verified"))

    for req in a.requirements:
        for fid in req.fact_ids:
            fact_ok(fid, f"requirement {req.text[:40]!r}")
        for bid in req.block_ids:
            if bid not in block_ids:
                errs.append(CheckError(rule="block", detail=f"requirement {req.text[:40]!r}: unknown block {bid}"))
        if req.status != "gap" and not (req.fact_ids or req.block_ids):
            errs.append(CheckError(rule="requirement", detail=f"{req.text[:40]!r}: status {req.status} needs fact_ids or block_ids"))
    for fid in a.candidate_facts:
        fact_ok(fid, "candidate_facts")
    scored = [r.block_id for r in a.relevance]
    for bid in scored:
        if bid not in block_ids:
            errs.append(CheckError(rule="relevance", detail=f"unknown block {bid}"))
    for b in resume.blocks:
        if b.editable and b.kind in RELEVANCE_KINDS and scored.count(b.id) != 1:
            errs.append(CheckError(rule="relevance", detail=f"block {b.id} must be scored exactly once (got {scored.count(b.id)})"))
    return errs


def parse_plan_ops(raw: AiPlan) -> tuple[list[Op], list[CheckError]]:
    ops: list[Op] = []
    errs: list[CheckError] = []
    seen: set[int] = set()
    for item in raw.ops:
        op_id = item.get("id") if isinstance(item.get("id"), int) else None
        try:
            op = AiOp.model_validate(item).to_op()
        except ValidationError as exc:
            for e in _errors(exc):
                errs.append(e.model_copy(update={"op": op_id}))
            continue
        except ValueError as exc:
            errs.append(CheckError(rule="schema", detail=str(exc), op=op_id))
            continue
        if op.id in seen:
            errs.append(CheckError(rule="schema", detail=f"duplicate op id {op.id}", op=op.id))
            continue
        seen.add(op.id)
        ops.append(op)
    return ops, errs
