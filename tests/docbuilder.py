"""Build synthetic Google Docs `documents.get` JSON for tests.

Indices are assigned in UTF-16 code units, like the real API: index 0 is the
section break, the first element starts at 1.
"""

from __future__ import annotations

PLAIN = {"fontSize": {"magnitude": 10, "unit": "PT"}}


def _u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def para(
    text: str,
    style: str = "NORMAL_TEXT",
    list_id: str | None = None,
    nesting: int | None = None,
    runs: list[tuple[str, dict]] | None = None,
    pstyle: dict | None = None,
) -> dict:
    """A paragraph spec. `text` has no trailing newline; `runs` overrides `text`."""
    runs = list(runs) if runs is not None else [(text, dict(PLAIN))]
    return {"kind": "para", "runs": runs, "style": style, "list_id": list_id, "nesting": nesting, "pstyle": pstyle or {}}


def table(cells: list[str]) -> dict:
    return {"kind": "table", "cells": cells}


def _render_para(spec: dict, start: int) -> tuple[dict, int]:
    runs = [(t, s) for t, s in spec["runs"] if t]
    last_style = runs[-1][1] if runs else dict(PLAIN)
    runs.append(("\n", dict(last_style)))
    elements, pos = [], start
    for content, ts in runs:
        n = _u16(content)
        elements.append({"startIndex": pos, "endIndex": pos + n, "textRun": {"content": content, "textStyle": dict(ts)}})
        pos += n
    paragraph = {
        "elements": elements,
        "paragraphStyle": {"namedStyleType": spec["style"], **spec["pstyle"]},
    }
    if spec["list_id"] is not None:
        bullet = {"listId": spec["list_id"]}
        if spec["nesting"]:
            bullet["nestingLevel"] = spec["nesting"]
        paragraph["bullet"] = bullet
    return {"startIndex": start, "endIndex": pos, "paragraph": paragraph}, pos


def _render_table(spec: dict, start: int) -> tuple[dict, int]:
    pos = start + 1
    cells = []
    for text in spec["cells"]:
        p, pos = _render_para(para(text), pos)
        cells.append({"content": [p]})
    end = pos + 1
    return {"startIndex": start, "endIndex": end, "table": {"tableRows": [{"tableCells": cells}]}}, end


def doc(*elements: dict, revision: str | None = "rev-1", doc_id: str = "doc-1") -> dict:
    content = [{"endIndex": 1, "sectionBreak": {"sectionStyle": {}}}]
    pos = 1
    for spec in elements:
        render = _render_table if spec["kind"] == "table" else _render_para
        el, pos = render(spec, pos)
        content.append(el)
    out = {"documentId": doc_id, "title": "Test doc", "body": {"content": content}}
    if revision is not None:
        out["revisionId"] = revision
    return out
