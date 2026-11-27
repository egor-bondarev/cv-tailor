"""Read-only view over Google Docs `documents.get` JSON."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from pydantic import BaseModel

STYLE_KEYS = (
    "bold",
    "italic",
    "underline",
    "strikethrough",
    "fontSize",
    "weightedFontFamily",
    "foregroundColor",
    "backgroundColor",
    "baselineOffset",
    "link",
)
_BOOL_KEYS = {"bold", "italic", "underline", "strikethrough"}
_COLOR_KEYS = {"foregroundColor", "backgroundColor"}


class DocFormatError(ValueError):
    pass


def utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _find_body(doc: dict) -> list[dict] | None:
    body = doc.get("body", {}).get("content")
    if body is not None:
        return body
    tabs = doc.get("tabs") or []
    if tabs:
        return tabs[0].get("documentTab", {}).get("body", {}).get("content")
    return None


def load_doc(data: dict, require_revision: bool = False) -> dict:
    """Return a bare `documents.get` dict; accept a `{"content": ...}` wrapper."""
    if "documentId" not in data and isinstance(data.get("content"), dict):
        data = data["content"]
    if "documentId" not in data:
        raise DocFormatError("not a documents.get response: no documentId")
    if _find_body(data) is None:
        raise DocFormatError(f"document {data['documentId']}: no body content")
    if require_revision and not data.get("revisionId"):
        raise DocFormatError(f"document {data['documentId']}: no revisionId (edit access required)")
    return data


def body_content(doc: dict) -> list[dict]:
    body = _find_body(doc)
    if body is None:
        raise DocFormatError("no body content")
    return body


class Paragraph(BaseModel):
    start: int
    end: int
    text: str
    named_style: str
    list_id: str | None
    nesting: int | None
    raw: dict

    @property
    def body_text(self) -> str:
        return self.text[:-1] if self.text.endswith("\n") else self.text


def _paragraph(el: dict) -> Paragraph:
    p = el["paragraph"]
    text = "".join(r.get("textRun", {}).get("content", "") for r in p.get("elements", []))
    bullet = p.get("bullet")
    return Paragraph(
        start=el.get("startIndex", 0),
        end=el["endIndex"],
        text=text,
        named_style=p.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT"),
        list_id=bullet.get("listId") if bullet else None,
        nesting=bullet.get("nestingLevel", 0) if bullet else None,
        raw=p,
    )


def paragraphs(doc: dict) -> list[Paragraph]:
    return [_paragraph(el) for el in body_content(doc) if "paragraph" in el]


class TableInfo(BaseModel):
    start: int
    end: int
    text: str


def _cell_text(content: list[dict]) -> str:
    out = []
    for el in content:
        if "paragraph" in el:
            out.append(_paragraph(el).body_text)
        elif "table" in el:
            out.append(_table_text(el["table"]))
    return "".join(out)


def _table_text(t: dict) -> str:
    return "".join(_cell_text(c.get("content", [])) for row in t.get("tableRows", []) for c in row.get("tableCells", []))


def iter_elements(doc: dict) -> list[Paragraph | TableInfo]:
    """Top-level paragraphs and tables in document order."""
    out: list[Paragraph | TableInfo] = []
    for el in body_content(doc):
        if "paragraph" in el:
            out.append(_paragraph(el))
        elif "table" in el:
            out.append(TableInfo(start=el.get("startIndex", 0), end=el["endIndex"], text=_table_text(el["table"])))
    return out


def tables(doc: dict) -> list[TableInfo]:
    return [
        TableInfo(start=el.get("startIndex", 0), end=el["endIndex"], text=_table_text(el["table"]))
        for el in body_content(doc)
        if "table" in el
    ]


def _hashable(v: Any) -> Any:
    return json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v


def norm_style(text_style: dict) -> tuple:
    out = []
    for k in STYLE_KEYS:
        v = text_style.get(k)
        if k in _BOOL_KEYS and v is False:
            v = None
        elif k in _COLOR_KEYS and v is not None:
            if not v or not v.get("color") or not v["color"].get("rgbColor"):
                v = None
        elif k == "baselineOffset" and v == "NONE":
            v = None
        elif k == "link" and not v:
            v = None
        out.append(_hashable(v))
    return tuple(out)


class ParaSnapshot(BaseModel):
    named_style: str
    paragraph_style: dict
    list_id: str | None
    nesting: int | None
    style_runs: list[tuple[int, tuple]]


def _style_runs(p: Paragraph) -> list[tuple[int, tuple]]:
    runs: list[tuple[int, tuple]] = []
    elements = [e for e in p.raw.get("elements", []) if "textRun" in e]
    for i, e in enumerate(elements):
        content = e["textRun"]["content"]
        if i == len(elements) - 1 and content.endswith("\n"):
            content = content[:-1]
        n = utf16_len(content)
        if not n:
            continue
        st = norm_style(e["textRun"].get("textStyle", {}))
        if runs and runs[-1][1] == st:
            runs[-1] = (runs[-1][0] + n, st)
        else:
            runs.append((n, st))
    return runs


# Not compared: heading ids are per document, and `final --fix-layout` moves page breaks (v2 V4).
UNCOMPARED_PARAGRAPH_KEYS = {"headingId", "pageBreakBefore"}


def snapshot(p: Paragraph) -> ParaSnapshot:
    ps = {k: v for k, v in p.raw.get("paragraphStyle", {}).items() if k not in UNCOMPARED_PARAGRAPH_KEYS}
    return ParaSnapshot(
        named_style=p.named_style,
        paragraph_style=ps,
        list_id=p.list_id,
        nesting=p.nesting,
        style_runs=_style_runs(p),
    )


def styles_in_range(snap: ParaSnapshot, start: int, end: int) -> list[tuple[int, tuple]]:
    out: list[tuple[int, tuple]] = []
    pos = 0
    for n, st in snap.style_runs:
        lo, hi = max(pos, start), min(pos + n, end)
        if lo < hi:
            out.append((hi - lo, st))
        pos += n
    return out


def dominant_style(runs: list[tuple[int, tuple]]) -> tuple:
    if not runs:
        return norm_style({})
    total: Counter = Counter()
    for n, st in runs:
        total[st] += n
    return total.most_common(1)[0][0]


def has_suggestions(doc: dict) -> list[str]:
    """Paths of every non-empty `suggested*` key anywhere in the document."""
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{path}.{k}" if path else k
                if k.startswith("suggested") and v:
                    found.append(p)
                else:
                    walk(v, p)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(doc, "")
    return found
