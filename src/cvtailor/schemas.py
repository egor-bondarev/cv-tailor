"""Pydantic models for JSON written by AI steps (DESIGN.md §6, §8)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cvtailor.models import Op, OpKind


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


HookType = Literal["mission", "product", "challenge", "scale"]


class HookCandidate(_Strict):
    """A sentence in which the company talks about itself, quoted verbatim from the vacancy (v2 V6)."""

    quote: str
    type: HookType
    strength: Literal["strong", "weak"]
    why: str = ""


class Vacancy(_Strict):
    title: str
    company: str | None = None
    seniority: str | None = None
    language: str
    summary: str
    must_have: list[str] = Field(min_length=1)
    nice_to_have: list[str] = []
    responsibilities: list[str] = []
    skills: list[str] = []
    domain: str | None = None
    location: str | None = None
    hooks: list[HookCandidate] = []


class Route(_Strict):
    choice: str
    confidence: Literal["high", "medium", "low"]
    ranking: list[str]
    reason: str


class Requirement(_Strict):
    text: str
    kind: Literal["must", "nice"]
    status: Literal["covered", "in_facts", "partial", "gap"]
    fact_ids: list[str] = []
    block_ids: list[str] = []


class Relevance(_Strict):
    block_id: str
    score: int = Field(ge=0, le=3)
    reason: str = ""


class Analysis(_Strict):
    requirements: list[Requirement]
    relevance: list[Relevance]
    candidate_facts: list[str]
    notes: str = ""


class AiOp(_Strict):
    id: int
    op: OpKind
    block: str | None = None
    after: str | None = None
    new_text: str | None = None
    new_value: str | None = None
    evidence: list[str] = []
    reason: str = ""

    def to_op(self) -> Op:
        return Op(**self.model_dump())


class AiPlan(_Strict):
    ops: list[dict]


class Verdict(_Strict):
    op: int
    verdict: Literal["supported", "partial", "unsupported"]
    quote: str = ""
    comment: str = ""


class Review(_Strict):
    verdicts: list[Verdict]


class LetterHook(_Strict):
    quote: str
    type: HookType
    strength: Literal["strong", "weak"]
    bridge: str  # a verified fact id or a profile motivation id


class LetterParagraph(_Strict):
    part: Literal["intro", "value", "motivation", "closing"]
    text: str
    facts: list[str] = []
    motivation: list[str] = []


class LetterRelocation(_Strict):
    mentioned: bool = False
    reason: str = ""


class LetterAi(_Strict):
    language: str
    greeting: str
    paragraphs: list[LetterParagraph] = Field(min_length=3)
    sign_off: str
    hook: LetterHook | None = None
    relocation: LetterRelocation = LetterRelocation()
    notes: str = ""
