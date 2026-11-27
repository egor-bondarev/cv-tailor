"""Split a resume Google Doc into addressable blocks (DESIGN.md §10.1)."""

from __future__ import annotations

import hashlib
from collections import defaultdict

from cvtailor.docmodel import Paragraph, TableInfo, has_suggestions, iter_elements, load_doc, utf16_len
from cvtailor.models import Block, ParsedResume, ParseError
from cvtailor.naming import slug

REQUIRED_SECTIONS = ("SUMMARY", "TECHNICAL SKILLS", "EXPERIENCE")
EXPERIENCE_PREFIX = {"EXPERIENCE": "exp", "EARLIER EXPERIENCE": "early"}
HEADINGS = {"HEADING_1", "HEADING_2", "HEADING_3"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def company_priority(spec: list[str] | dict[str, int], company: str, index: int, earlier_unlisted: int) -> int:
    """Edit priority of the `index`-th EXPERIENCE company (0 = most recent); 0 means read-only."""
    if isinstance(spec, dict):
        return max(0, int({slug(k): v for k, v in spec.items()}.get(company, 0)))
    listed = {slug(c) for c in spec}
    if listed:
        return 1 if company in listed else 2 + earlier_unlisted
    return 1 if index < 2 else index


class _Parser:
    def __init__(self, editable_companies: list[str] | dict[str, int]):
        self.spec = editable_companies
        self.exp_companies: list[str] = []
        self.unlisted = 0
        self.priority = 0
        self.blocks: list[Block] = []
        self.section: str | None = None
        self.sections_seen: set[str] = set()
        self.counters: dict[str, int] = defaultdict(int)
        self.used: dict[str, int] = defaultdict(int)
        self.company: str | None = None
        self.role: str | None = None
        self._reset_role()

    def _reset_role(self) -> None:
        self.intro_done = False
        self.seen_bullet = False
        self.last_bullet: Block | None = None

    def next_no(self, key: str) -> int:
        self.counters[key] += 1
        return self.counters[key]

    def unique(self, scope: str, name: str) -> str:
        self.used[(scope, name)] += 1
        n = self.used[(scope, name)]
        return name if n == 1 else f"{name}-{n}"

    def add(self, block_id: str, kind: str, p: Paragraph | TableInfo, text: str, editable: bool = False, **kw) -> None:
        self.blocks.append(
            Block(id=block_id, kind=kind, editable=editable, start=p.start, end=p.end, text=text, sha=_sha(text), **kw)
        )

    # --- elements -------------------------------------------------------

    def table(self, t: TableInfo) -> None:
        self.add(f"table.{self.next_no('table'):02d}", "readonly", t, t.text)

    def paragraph(self, p: Paragraph) -> None:
        text = p.body_text
        if not text.strip():
            return
        list_kw = {"list_id": p.list_id, "nesting": p.nesting}
        if p.named_style in ("TITLE", "SUBTITLE"):
            if self.counters[p.named_style]:
                raise ParseError(f"more than one {p.named_style} paragraph: {text[:50]!r}")
            self.counters[p.named_style] += 1
            if p.named_style == "TITLE":
                return self.add("name", "readonly", p, text)
            return self.add("title", "title", p, text, editable=True)
        if p.named_style in HEADINGS:
            self.add(f"h.{self.next_no('h'):03d}", "readonly", p, text)
            return self.heading(p.named_style, text)
        if self.section is None:
            return self.add(f"contact.{self.next_no('contact'):02d}", "readonly", p, text)
        if self.section == "SUMMARY":
            if self.counters["summary"]:
                raise ParseError(f"SUMMARY must have exactly one paragraph, found another: {text[:50]!r}")
            self.counters["summary"] += 1
            return self.add("summary", "summary", p, text, editable=True)
        if self.section == "TECHNICAL SKILLS":
            if ": " not in text:
                raise ParseError(f"TECHNICAL SKILLS line without 'Category: ': {text[:50]!r}")
            category = text[: text.index(": ")]
            label_len = utf16_len(text[: text.index(": ") + 2])
            sid = self.unique("skills", slug(category))
            return self.add(f"skills.{sid}", "skills", p, text, editable=True, label_len=label_len)
        if self.section in EXPERIENCE_PREFIX:
            return self.experience(p, text, list_kw)
        sec = slug(self.section)
        self.add(f"ro.{sec}.{self.next_no('ro.' + sec):02d}", "readonly", p, text, **list_kw)

    def heading(self, style: str, text: str) -> None:
        if style == "HEADING_1":
            self.section = text.strip().upper()
            self.sections_seen.add(self.section)
            self.company = self.role = None
            self._reset_role()
        elif style == "HEADING_2" and self.section in EXPERIENCE_PREFIX:
            prefix = EXPERIENCE_PREFIX[self.section]
            self.company = self.unique(prefix, slug(text.split("|")[0]))
            self.priority = 0
            if prefix == "exp":
                self.priority = company_priority(self.spec, self.company, len(self.exp_companies), self.unlisted)
                if isinstance(self.spec, list) and self.spec and self.company not in {slug(c) for c in self.spec}:
                    self.unlisted += 1
                self.exp_companies.append(self.company)
            self.role = None
            self._reset_role()
        elif style == "HEADING_3" and self.section in EXPERIENCE_PREFIX and self.company:
            self.role = self.unique(f"role.{self.company}", slug(text.rsplit("|", 1)[0]))
            self._reset_role()

    def experience(self, p: Paragraph, text: str, list_kw: dict) -> None:
        prefix = EXPERIENCE_PREFIX[self.section]
        if self.company is None:
            sec = slug(self.section)
            return self.add(f"ro.{sec}.{self.next_no('ro.' + sec):02d}", "readonly", p, text, **list_kw)
        base = f"{prefix}.{self.company}" + (f".{self.role}" if self.role else "")
        can_edit = prefix == "exp" and self.priority > 0 and self.role is not None
        owner = {"company": self.company, "role": self.role, **({"priority": self.priority} if can_edit else {})}
        if self.role is None and p.list_id is None and not self.seen_bullet:
            return self.add(f"{base}.desc{self.next_no(base + '.desc'):02d}", "readonly", p, text, **owner)
        if p.list_id is None:
            if self.role is not None and not self.intro_done and not self.seen_bullet:
                self.intro_done = True
                return self.add(f"{base}.intro", "intro", p, text, editable=can_edit, **owner)
            return self.add(f"{base}.p{self.next_no(base + '.p'):02d}", "readonly", p, text, **owner)
        if p.nesting:
            if self.last_bullet is not None:
                self.last_bullet.has_children = True
            return self.add(f"{base}.s{self.next_no(base + '.s'):02d}", "readonly", p, text, **owner, **list_kw)
        self.seen_bullet = True
        bid = f"{base}.b{self.next_no(base + '.b'):02d}"
        self.add(bid, "bullet", p, text, editable=can_edit, **owner, **list_kw)
        self.last_bullet = self.blocks[-1]


def parse_resume(doc: dict, editable_companies: list[str] | dict[str, int]) -> ParsedResume:
    doc = load_doc(doc)
    pending = has_suggestions(doc)
    if pending:
        raise ParseError(f"document has pending suggestions, resolve them first: {pending[:3]}")
    parser = _Parser(editable_companies)
    elements = iter_elements(doc)
    for el in elements:
        if isinstance(el, Paragraph):
            parser.paragraph(el)
        else:
            parser.table(el)
    boundary = {
        el.start for el, nxt in zip(elements, elements[1:] + [None])
        if isinstance(el, Paragraph) and (nxt is None or not isinstance(nxt, Paragraph))
    }
    for b in parser.blocks:
        b.at_boundary = b.start in boundary
    missing = [s for s in REQUIRED_SECTIONS if s not in parser.sections_seen]
    if missing:
        raise ParseError(f"missing section: {', '.join(missing)}")
    if not parser.counters["summary"]:
        raise ParseError("SUMMARY must have exactly one paragraph, found none")
    return ParsedResume(document_id=doc["documentId"], revision_id=doc.get("revisionId"), blocks=parser.blocks)
