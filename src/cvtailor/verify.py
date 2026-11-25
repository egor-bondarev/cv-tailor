"""Check that applied suggestions produced exactly the expected document (DESIGN.md §10.4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cvtailor.docmodel import (
    Paragraph,
    dominant_style,
    has_suggestions,
    load_doc,
    paragraphs,
    snapshot,
    styles_in_range,
    tables,
    utf16_len,
)
from cvtailor.models import Op, ParsedResume, ParseError, VerifyReport
from cvtailor.parse import parse_resume

Kind = Literal["same", "replaced", "skills", "inserted"]


@dataclass
class _Expected:
    text: str
    kind: Kind
    src: Paragraph
    label_len: int = 0


def _short(text: str) -> str:
    return repr(text.rstrip("\n")[:50])


def _aligned(before_doc: dict, resume: ParsedResume, ops: list[Op]) -> list[_Expected]:
    by_start = {b.start: b for b in resume.blocks}
    edits = {op.block: op for op in ops if op.op != "insert_after"}
    inserts: dict[str, list[Op]] = {}
    for op in sorted((o for o in ops if o.op == "insert_after"), key=lambda o: o.id):
        inserts.setdefault(op.after, []).append(op)

    out: list[_Expected] = []
    for p in paragraphs(load_doc(before_doc)):
        block = by_start.get(p.start)
        op = edits.get(block.id) if block else None
        if op is None:
            out.append(_Expected(p.text, "same", p))
        elif op.op == "replace":
            out.append(_Expected(op.new_text + "\n", "replaced", p))
        elif op.op == "replace_skills":
            label = block.text[: block.text.index(": ") + 2]
            out.append(_Expected(label + op.new_value + "\n", "skills", p, label_len=block.label_len))
        for ins in inserts.get(block.id, []) if block else []:
            out.append(_Expected(ins.new_text + "\n", "inserted", p))
    return out


def expected_texts(before_doc: dict, resume: ParsedResume, ops: list[Op]) -> list[str]:
    return [e.text for e in _aligned(before_doc, resume, ops)]


def _structure_problems(src: Paragraph, got: Paragraph) -> list[str]:
    a, b = snapshot(src), snapshot(got)
    fields = [f for f in ("named_style", "paragraph_style", "list_id", "nesting") if getattr(a, f) != getattr(b, f)]
    return [f"{_short(got.text)}: {', '.join(fields)} differ from reference {_short(src.text)}"] if fields else []


def _single_style_problem(got_runs, ref_runs, got: Paragraph, what: str) -> list[str]:
    want = dominant_style(ref_runs)
    if len({st for _, st in got_runs}) > 1 or (got_runs and got_runs[0][1] != want):
        return [f"{_short(got.text)}: {what} text style differs from reference style"]
    return []


def verify_applied(before_doc: dict, preview_doc: dict, resume: ParsedResume, ops: list[Op]) -> VerifyReport:
    expected = _aligned(before_doc, resume, ops)
    got = paragraphs(load_doc(preview_doc))
    want_texts, got_texts = [e.text for e in expected], [p.text for p in got]
    if want_texts != got_texts:
        for i, (w, g) in enumerate(zip(want_texts, got_texts)):
            if w != g:
                return VerifyReport(ok=False, problems=[f"text differs at paragraph {i}: expected {_short(w)}, got {_short(g)}"])
        return VerifyReport(ok=False, problems=[f"text differs: expected {len(want_texts)} paragraphs, got {len(got_texts)}"])

    problems: list[str] = []
    if [t.text for t in tables(load_doc(before_doc))] != [t.text for t in tables(load_doc(preview_doc))]:
        problems.append("table content changed")

    for e, g in zip(expected, got):
        if e.kind == "same":
            if snapshot(e.src) != snapshot(g):
                problems.append(f"{_short(g.text)}: style changed in untouched paragraph")
            continue
        problems += _structure_problems(e.src, g)
        src_snap, got_snap = snapshot(e.src), snapshot(g)
        if e.kind == "skills":
            n_src = utf16_len(e.src.body_text)
            n_got = utf16_len(g.body_text)
            if styles_in_range(got_snap, 0, e.label_len) != styles_in_range(src_snap, 0, e.label_len):
                problems.append(f"{_short(g.text)}: skills label style changed")
            problems += _single_style_problem(
                styles_in_range(got_snap, e.label_len, n_got), styles_in_range(src_snap, e.label_len, n_src), g, "skills value"
            )
        else:
            problems += _single_style_problem(got_snap.style_runs, src_snap.style_runs, g, e.kind)
    return VerifyReport(ok=not problems, problems=problems)


def final_check(
    before_doc: dict, final_doc: dict, resume: ParsedResume, editable_companies: list[str]
) -> VerifyReport:
    final_doc = load_doc(final_doc)
    pending = has_suggestions(final_doc)
    if pending:
        return VerifyReport(ok=False, problems=[f"unresolved suggestions: {pending[:3]}"])
    try:
        final = parse_resume(final_doc, editable_companies)
    except ParseError as exc:
        return VerifyReport(ok=False, problems=[f"cannot parse final document: {exc}"])

    problems: list[str] = []
    before_paras = {p.start: p for p in paragraphs(load_doc(before_doc))}
    final_paras = {p.start: p for p in paragraphs(final_doc)}
    final_blocks = {b.id: b for b in final.blocks}

    for b in resume.blocks:
        if b.editable:
            continue
        nb = final_blocks.get(b.id)
        if nb is None:
            problems.append(f"{b.id}: read-only block missing")
        elif nb.sha != b.sha:
            problems.append(f"{b.id}: read-only text changed: {_short(nb.text)}")
        elif b.start in before_paras and nb.start in final_paras:
            if snapshot(before_paras[b.start]) != snapshot(final_paras[nb.start]):
                problems.append(f"{b.id}: read-only style changed")

    known = {b.id for b in resume.blocks}
    for nb in final.blocks:
        if not nb.editable and nb.id not in known:
            problems.append(f"{nb.id}: read-only content added: {_short(nb.text)}")

    roles = {(b.company, b.role) for b in resume.blocks if b.editable and b.kind == "bullet"}
    for company, role in sorted(roles, key=str):
        ref = resume.role_bullets(company, role)[0]
        for nb in final.role_bullets(company, role):
            if (nb.list_id, nb.nesting) != (ref.list_id, ref.nesting):
                problems.append(f"{nb.id}: bullet left its role list ({nb.list_id} != {ref.list_id})")
    return VerifyReport(ok=not problems, problems=problems)
