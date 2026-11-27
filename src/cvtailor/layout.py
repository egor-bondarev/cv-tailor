"""Keep each experience role on one page (v2 V4).

The Docs API has no page layout, so the copy is exported to PDF (Google renders it like Docs does) and the text
of each page is matched back to the document's paragraphs. A role that starts on one page and ends on the next
gets a page break before its heading; a manual page break right after the role, which would now leave a
near-empty page, is removed.
"""

from __future__ import annotations

import io
import unicodedata
from dataclasses import dataclass, field
from typing import Protocol

from cvtailor.docmodel import Paragraph, load_doc, paragraphs
from cvtailor.parse import EXPERIENCE_PREFIX, HEADINGS

KEY_CHARS = 40


class LayoutClient(Protocol):
    def get_doc(self, doc_id: str) -> dict: ...
    def export_pdf(self, file_id: str) -> bytes: ...
    def batch_update(self, doc_id: str, body: dict) -> dict: ...


def pdf_pages(data: bytes) -> list[str]:
    import pypdf

    return [page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(data)).pages]


def _norm(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", text).lower() if ch.isalnum())


@dataclass
class Unit:
    """A role with the headings above it (section, company, company description) that must stay with it."""

    label: str
    paras: list[Paragraph] = field(default_factory=list)


def units(doc: dict) -> list[Unit]:
    out: list[Unit] = []
    section = company = None
    cur: Unit | None = None
    in_head = False
    last_heading = None
    for p in paragraphs(load_doc(doc)):
        text = p.body_text.strip()
        if not text:
            continue
        if p.named_style == "HEADING_1":
            section = text.upper()
            company = None
        if section not in EXPERIENCE_PREFIX:
            cur, in_head = None, False
            continue
        if p.named_style in HEADINGS:
            if p.named_style == "HEADING_2":
                company = text.split("|")[0].strip()
            if not in_head:
                cur = Unit(label="")
                out.append(cur)
                in_head = True
            last_heading = p.named_style
            cur.paras.append(p)
            role = text.rsplit("|", 1)[0].strip() if p.named_style == "HEADING_3" else None
            cur.label = f"{role} ({company})" if role and company else (company or text)
            continue
        if cur is None:
            continue
        if in_head and last_heading == "HEADING_2" and p.list_id is None:
            cur.paras.append(p)  # company description
            continue
        in_head = False
        cur.paras.append(p)
    return [u for u in out if any(p.named_style not in HEADINGS for p in u.paras)]


def paragraph_pages(doc: dict, pages: list[str]) -> dict[int, tuple[int, int]]:
    """Paragraph start index -> (first page, last page), 0-based; paragraphs not found in the PDF are left out."""
    stream, bounds = "", []
    for text in pages:
        stream += _norm(text)
        bounds.append(len(stream))

    def page_of(pos: int) -> int:
        return next(i for i, end in enumerate(bounds) if pos < end)

    out: dict[int, tuple[int, int]] = {}
    cursor = 0
    for p in paragraphs(load_doc(doc)):
        key = _norm(p.body_text)
        if not key:
            continue
        head, tail = key[:KEY_CHARS], key[-KEY_CHARS:]
        start = stream.find(head, cursor)
        if start < 0:
            continue
        if len(key) <= KEY_CHARS:
            end = start + len(key) - 1
        else:
            end = stream.find(tail, start + 1)
            if end < 0:
                continue
            end += len(tail) - 1
        out[p.start] = (page_of(start), page_of(end))
        cursor = end + 1
    return out


@dataclass
class Split:
    unit: Unit
    first_page: int
    last_page: int
    starts_page: bool  # the role already starts a page: it is longer than one page and cannot be fixed


def find_split(doc: dict, pages: list[str]) -> Split | None:
    where = paragraph_pages(doc, pages)
    order = [p.start for p in paragraphs(load_doc(doc)) if p.start in where]
    for u in units(doc):
        found = [where[p.start] for p in u.paras if p.start in where]
        if not found:
            continue
        first, last = found[0][0], max(end for _, end in found)
        if first == last:
            continue
        head = next(p.start for p in u.paras if p.start in where)
        i = order.index(head)
        starts_page = u.paras[0].raw.get("paragraphStyle", {}).get("pageBreakBefore") is True or (
            i > 0 and where[order[i - 1]][1] < first
        )
        return Split(u, first, last, starts_page)
    return None


def _break_elements(p: Paragraph) -> list[dict]:
    return [e for e in p.raw.get("elements", []) if "pageBreak" in e]


def fix_requests(doc: dict, unit: Unit) -> tuple[list[dict], list[str]]:
    """Requests that start `unit` on a new page and drop a manual page break right after it, plus what they do."""
    paras = paragraphs(load_doc(doc))
    last = unit.paras[-1]
    after: list[Paragraph] = [last]
    for p in paras:
        if p.start <= last.start:
            continue
        after.append(p)
        if p.body_text.strip():
            break
    deletes = [e for p in after for e in _break_elements(p)]
    requests: list[dict] = [
        {"deleteContentRange": {"range": {"startIndex": e["startIndex"], "endIndex": e["endIndex"]}}}
        for e in sorted(deletes, key=lambda e: -e["startIndex"])
    ]
    notes = [f"moved {unit.label} to the next page"]
    if deletes:
        notes.append(f"removed {len(deletes)} page break(s) after it")
    nxt = after[-1] if after[-1] is not last else None
    if nxt is not None and nxt.raw.get("paragraphStyle", {}).get("pageBreakBefore") is True:
        requests.append({"updateParagraphStyle": {"range": {"startIndex": nxt.start, "endIndex": nxt.end},
                                                  "paragraphStyle": {"pageBreakBefore": False},
                                                  "fields": "pageBreakBefore"}})
        notes.append(f"removed the page break before {nxt.body_text.split('|')[0].strip()!r}")
    head = unit.paras[0]
    requests.append({"updateParagraphStyle": {"range": {"startIndex": head.start, "endIndex": head.end},
                                              "paragraphStyle": {"pageBreakBefore": True},
                                              "fields": "pageBreakBefore"}})
    return requests, notes


@dataclass
class LayoutResult:
    split: str = ""  # the role still split after the last round ("" if none)
    pages: str = ""
    fixed: list[str] = field(default_factory=list)
    problem: str = ""

    def text(self, fix: bool) -> str:
        parts = []
        if self.fixed:
            parts.append("Layout fixed: " + "; ".join(self.fixed) + ".")
        if self.problem:
            parts.append(f"Layout: {self.problem}.")
        elif self.split:
            hint = "" if fix else "; run `cvtailor final --fix-layout` to move it to the next page"
            parts.append(f"Layout: {self.split} is split across pages {self.pages}{hint}.")
        elif not self.fixed:
            parts.append("Layout: no role is split across pages.")
        return " ".join(parts)


def check_layout(client: LayoutClient, doc_id: str, fix: bool, max_rounds: int = 5) -> LayoutResult:
    res = LayoutResult()
    for _ in range(max_rounds):
        doc = client.get_doc(doc_id)
        split = find_split(doc, pdf_pages(client.export_pdf(doc_id)))
        res.split = res.pages = ""
        if split is None:
            return res
        res.split, res.pages = split.unit.label, f"{split.first_page + 1}-{split.last_page + 1}"
        if not fix:
            return res
        if split.starts_page:
            res.problem = f"{split.unit.label} already starts a page and is longer than one page"
            return res
        requests, notes = fix_requests(doc, split.unit)
        body = {"requests": requests}
        if doc.get("revisionId"):
            body["writeControl"] = {"requiredRevisionId": doc["revisionId"]}
        client.batch_update(doc_id, body)
        res.fixed += notes
    res.problem = f"still split after {max_rounds} rounds"
    return res
