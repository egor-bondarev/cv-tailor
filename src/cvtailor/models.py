"""Data models shared across cvtailor modules."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

BlockKind = Literal["title", "summary", "skills", "intro", "bullet", "readonly"]


class ParseError(ValueError):
    pass


class Block(BaseModel):
    id: str
    kind: BlockKind
    editable: bool
    start: int
    end: int
    text: str
    sha: str
    company: str | None = None
    role: str | None = None
    label_len: int = 0
    list_id: str | None = None
    nesting: int | None = None
    has_children: bool = False
    at_boundary: bool = False


class ParsedResume(BaseModel):
    document_id: str
    revision_id: str | None
    blocks: list[Block]

    def get(self, block_id: str) -> Block:
        for b in self.blocks:
            if b.id == block_id:
                return b
        raise KeyError(f"unknown block: {block_id}")

    def role_bullets(self, company: str, role: str) -> list[Block]:
        return [
            b for b in self.blocks
            if b.kind == "bullet" and b.company == company and b.role == role and not b.nesting
        ]


class BuildError(ValueError):
    pass


OpKind = Literal["replace", "replace_skills", "insert_after", "delete"]
_REQUIRED_FIELDS = {
    "replace": ("block", "new_text"),
    "replace_skills": ("block", "new_value"),
    "insert_after": ("after", "new_text"),
    "delete": ("block",),
}


class Op(BaseModel):
    id: int
    op: OpKind
    block: str | None = None
    after: str | None = None
    new_text: str | None = None
    new_value: str | None = None
    evidence: list[str] = []
    reason: str = ""

    @model_validator(mode="after")
    def _required(self) -> "Op":
        missing = [f for f in _REQUIRED_FIELDS[self.op] if getattr(self, f) is None]
        if missing:
            raise ValueError(f"op {self.id} ({self.op}) requires {', '.join(missing)}")
        return self

    @property
    def target(self) -> str:
        return self.after if self.op == "insert_after" else self.block

    @property
    def text(self) -> str | None:
        return self.new_value if self.op == "replace_skills" else self.new_text


class VerifyReport(BaseModel):
    ok: bool
    problems: list[str]
