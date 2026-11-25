"""Turn edit operations into one Docs API batchUpdate body (DESIGN.md §10.2)."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from cvtailor.models import Block, BuildError, Op, ParsedResume

ALLOWED_KINDS = {
    "replace": {"title", "summary", "intro", "bullet"},
    "replace_skills": {"skills"},
    "insert_after": {"bullet"},
    "delete": {"bullet"},
}
EXCLUSIVE = {"replace", "replace_skills", "delete"}
FORBIDDEN_CHARS = {"\n": "newline", "\r": "newline", "\x0b": "newline"}


def _target(resume: ParsedResume, op: Op) -> Block:
    try:
        block = resume.get(op.target)
    except KeyError:
        raise BuildError(f"op {op.id}: unknown block {op.target}") from None
    if not block.editable:
        raise BuildError(f"op {op.id}: block {block.id} is not editable")
    if block.kind not in ALLOWED_KINDS[op.op]:
        raise BuildError(f"op {op.id}: {op.op} not allowed on {block.kind} block {block.id}")
    return block


def check_ops(resume: ParsedResume, ops: list[Op]) -> None:
    exclusive: dict[str, int] = {}
    anchors: set[str] = set()
    deleted: set[str] = set()
    for op in ops:
        block = _target(resume, op)
        if op.op in ("insert_after", "delete") and block.has_children:
            raise BuildError(f"op {op.id}: {op.op} on {block.id} would detach its nested bullets")
        if op.op == "delete" and block.at_boundary:
            raise BuildError(
                f"op {op.id}: cannot delete {block.id}: it is the last paragraph before a table or the end of the document"
            )
        if op.op != "delete":
            text = op.text or ""
            if not text.strip():
                raise BuildError(f"op {op.id}: empty text")
            for ch, name in FORBIDDEN_CHARS.items():
                if ch in text:
                    raise BuildError(f"op {op.id}: {name} in new text")
        if op.op in EXCLUSIVE:
            if op.block in exclusive:
                raise BuildError(f"ops {exclusive[op.block]} and {op.id}: more than one edit of block {op.block}")
            exclusive[op.block] = op.id
        if op.op == "insert_after":
            anchors.add(op.after)
        if op.op == "delete":
            deleted.add(op.block)
    clash = anchors & deleted
    if clash:
        raise BuildError(f"insert_after anchor cannot be deleted: {sorted(clash)}")


def build_requests(
    resume: ParsedResume, ops: list[Op], mode: Literal["SUGGEST", "EDIT"] = "SUGGEST"
) -> dict:
    check_ops(resume, ops)
    if not resume.revision_id:
        raise BuildError("document revision is unknown: re-read the copy before building requests")

    groups: list[tuple[int, int, list[dict]]] = []
    inserts: dict[str, list[Op]] = defaultdict(list)
    for op in ops:
        b = resume.get(op.target)
        if op.op == "insert_after":
            inserts[b.id].append(op)
        elif op.op == "delete":
            groups.append((b.start, 0, [{"deleteContentRange": {"range": {"startIndex": b.start, "endIndex": b.end}}}]))
        else:
            start = b.start + (b.label_len if op.op == "replace_skills" else 0)
            groups.append((start, 0, [
                {"deleteContentRange": {"range": {"startIndex": start, "endIndex": b.end - 1}}},
                {"insertText": {"location": {"index": start}, "text": op.text}},
            ]))
    for anchor_id, anchor_ops in inserts.items():
        b = resume.get(anchor_id)
        text = "".join("\n" + o.new_text for o in sorted(anchor_ops, key=lambda o: o.id))
        groups.append((b.end - 1, 1, [{"insertText": {"location": {"index": b.end - 1}, "text": text}}]))

    groups.sort(key=lambda g: (g[0], g[1]), reverse=True)
    return {
        "requests": [r for _, _, reqs in groups for r in reqs],
        "writeControl": {"requiredRevisionId": resume.revision_id, "writeMode": mode},
    }
