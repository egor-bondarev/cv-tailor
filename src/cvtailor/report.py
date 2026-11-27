"""Run report (`review.md`), chat summary and acceptance statistics (DESIGN.md §11)."""

from __future__ import annotations

import difflib
from typing import Literal

from pydantic import BaseModel, ConfigDict

from cvtailor.checks import CheckError
from cvtailor.facts import FactsFile
from cvtailor.models import Op, ParsedResume, VerifyReport
from cvtailor.schemas import Analysis, Review, Route, Vacancy


class ReportData(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    vacancy: Vacancy
    resume_label: str
    route: Route | None
    doc_url: str
    analysis: Analysis
    applied: list[Op]
    dropped: list[tuple[Op, list[CheckError]]]
    resume: ParsedResume
    facts: FactsFile
    review: Review | None
    reviewer_status: str
    verify: VerifyReport
    notes: list[str] = []


def _gaps(d: ReportData) -> list[str]:
    return [r.text for r in d.analysis.requirements if r.kind == "must" and r.status == "gap"]


def _coverage(d: ReportData) -> str:
    """One line on how much of the must-have list the candidate's experience backs."""
    must = [r for r in d.analysis.requirements if r.kind == "must"]
    if not must:
        return ""
    backed = sum(r.status in ("covered", "in_facts") for r in must)
    partial = sum(r.status == "partial" for r in must)
    line = f"Must-have coverage: {backed}/{len(must)} backed, {partial} partial, {len(must) - backed - partial} gaps"
    if backed * 2 < len(must):
        line += " — weak match: less than half of the must-haves are backed by your experience"
    return line + "."


def _verdicts(d: ReportData) -> dict[int, object]:
    return {v.op: v for v in d.review.verdicts} if d.review else {}


def review_md(d: ReportData) -> str:
    scores = {r.block_id: r.score for r in d.analysis.relevance}
    facts = {f.id: f for f in d.facts.facts}
    verdicts = _verdicts(d)
    company = d.vacancy.company or "?"
    lines = [f"# Review: {d.resume_label} → {company} ({d.vacancy.title})", ""]
    route = f"{d.route.choice} (confidence: {d.route.confidence})" if d.route else "fixed by user"
    lines.append(f"Doc: {d.doc_url} · Resume: {route}")
    lines.append(f"Must-have gaps: {', '.join(_gaps(d)) or 'none'} · Reviewer: {d.reviewer_status}")
    if _coverage(d):
        lines.append(_coverage(d))
    lines.append("")
    for op in d.applied:
        b = d.resume.get(op.target)
        v = verdicts.get(op.id)
        head = f"## {op.id}. {op.op} · {op.target}"
        if op.target in scores:
            head += f" · relevance {scores[op.target]}"
        head += f" · reviewer: {v.verdict if v else 'n/a'}"
        lines += [head, ""]
        if op.op == "insert_after":
            lines.append(f"**After:** {b.text}")
        else:
            lines.append(f"**Was:** {b.text}")
        if op.op != "delete":
            lines.append(f"**New:** {op.new_text if op.op != 'replace_skills' else op.new_value}")
        ev = " · ".join(f"{fid} «{facts[fid].claim[:60]}…»" if fid in facts else fid for fid in op.evidence)
        lines.append(f"Evidence: {ev or '—'} · Reason: {op.reason or '—'}")
        if v and v.verdict != "supported":
            lines.append(f"Reviewer: {v.verdict} — «{v.quote}» {v.comment}".rstrip())
        lines.append("")
    if d.dropped:
        lines += ["## Not applied (invalid)", ""]
        for op, errs in d.dropped:
            reasons = "; ".join(f"{e.rule}: {e.detail}" for e in errs)
            lines.append(f"- op {op.id} {op.op} {op.target} — {reasons}")
        lines.append("")
    if not d.verify.ok:
        lines += ["## Verify FAILED", ""] + [f"- {p}" for p in d.verify.problems] + [""]
    return "\n".join(lines)


def summary_txt(d: ReportData) -> str:
    lines = [f"Resume copy: {d.doc_url}",
             f"{len(d.applied)} edits applied, {len(d.dropped)} dropped by validators (details in review.md)."]
    if _coverage(d):
        lines.append(_coverage(d))
    gaps = _gaps(d)
    if gaps:
        lines.append(f"Must-have gaps (not in your facts): {', '.join(gaps)}")
    flagged = [v for v in _verdicts(d).values() if v.verdict != "supported"]
    if flagged:
        lines.append("Check carefully: " + "; ".join(f"op {v.op} {v.verdict} «{v.quote}»" for v in flagged))
    lines.append(f"reviewer: {d.reviewer_status}")
    lines += [f"Note: {n}" for n in d.notes]
    if not d.verify.ok:
        lines.append(f"Verify FAILED, copy renamed [FAILED]: {'; '.join(d.verify.problems[:2])}")
    lines.append("Accept or reject every suggestion in Google Docs before sending the resume.")
    return "\n".join(lines) + "\n"


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def op_comment(op: Op, d: ReportData, index: int) -> tuple[str, str]:
    """(comment text, quoted text) explaining one edit; the quote is what the edit leaves in the document."""
    b = d.resume.get(op.target)
    facts = {f.id: f for f in d.facts.facts}
    v = _verdicts(d).get(op.id)
    score = next((r.score for r in d.analysis.relevance if r.block_id == op.target), None)
    head = f"cv-tailor · edit {index} of {len(d.applied)} · {op.op}"
    if score is not None and op.op != "insert_after":  # an insert's score would be its anchor's
        head += f" · relevance {score}"
    if op.op == "delete":
        quote, what = b.text, "Removed bullet."
    elif op.op == "insert_after":
        quote, what = op.new_text, f"New bullet after «{_clip(b.text, 60)}»."
    elif op.op == "replace_skills":
        quote, what = b.text[: b.text.index(": ") + 2] + op.new_value, f"Was: {_clip(b.text, 160)}"
    else:
        quote, what = op.new_text, f"Was: {_clip(b.text, 160)}"
    lines = [head, what, f"Why: {op.reason or '—'}"]
    for fid in op.evidence:
        lines.append(f"Fact {fid}: {_clip(facts[fid].claim, 140)}" if fid in facts else f"Fact {fid}")
    if v:
        line = f"Reviewer ({d.reviewer_status}): {v.verdict}"
        if v.verdict != "supported":
            line += f" — «{v.quote}» {v.comment}".rstrip()
        lines.append(line)
    return "\n".join(lines), quote


class OpOutcome(BaseModel):
    op: int
    outcome: Literal["accepted", "edited", "rejected"]


def acceptance(before: ParsedResume, final: ParsedResume, applied: list[Op]) -> list[OpOutcome]:
    out: dict[int, str] = {}
    pending: list[tuple[Op, str, tuple]] = []
    final_ids = {b.id: b for b in final.blocks}

    def role_texts(res: ParsedResume, key: tuple) -> list[str]:
        return [b.text for b in res.blocks if b.kind == "bullet" and (b.company, b.role) == key and not b.nesting]

    for op in applied:
        b = before.get(op.target)
        new = op.new_value if op.op == "replace_skills" else op.new_text
        if b.kind == "bullet":
            key = (b.company, b.role)
            texts = role_texts(final, key)
            if op.op == "delete":
                out[op.id] = "rejected" if b.text in texts else "accepted"
            elif new in texts:
                out[op.id] = "accepted"
            elif op.op == "replace" and b.text in texts:
                out[op.id] = "rejected"
            else:
                pending.append((op, new, key))
        else:
            fb = final_ids.get(b.id)
            got = fb.text if fb else ""
            if op.op == "replace_skills":
                got = got[got.index(": ") + 2:] if ": " in got else got
                orig = b.text[b.text.index(": ") + 2:]
            else:
                orig = b.text
            out[op.id] = "accepted" if got == new else "rejected" if got == orig else "edited"

    used: set[str] = set()
    for op, new, key in pending:
        known = set(role_texts(before, key)) | {o.new_text for o in applied if o.new_text}
        unknown = [t for t in role_texts(final, key) if t not in known and t not in used]
        best = max(unknown, key=lambda t: difflib.SequenceMatcher(None, new, t).ratio(), default=None)
        if best and difflib.SequenceMatcher(None, new, best).ratio() >= 0.5:
            used.add(best)
            out[op.id] = "edited"
        else:
            out[op.id] = "rejected"
    return [OpOutcome(op=i, outcome=o) for i, o in sorted(out.items())]
