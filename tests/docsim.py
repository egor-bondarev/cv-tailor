"""Build the PREVIEW_SUGGESTIONS_ACCEPTED document Google would return after applying ops (tests only)."""

from __future__ import annotations

from cvtailor.docmodel import load_doc
from cvtailor.verify import _aligned
from docbuilder import doc, para


def _runs(p) -> list[tuple[str, dict]]:
    out = []
    for e in p.raw.get("elements", []):
        tr = e.get("textRun")
        if tr:
            out.append((tr["content"].rstrip("\n"), tr.get("textStyle", {})))
    return [(t, s) for t, s in out if t]


def _dominant(runs):
    return max(runs, key=lambda r: len(r[0]))[1] if runs else {}


def preview_doc(before_doc: dict, resume, ops, revision: str = "rev-2") -> dict:
    before_doc = load_doc(before_doc)
    specs = []
    for e in _aligned(before_doc, resume, ops):
        src = e.src
        runs = _runs(src)
        ps = {k: v for k, v in src.raw.get("paragraphStyle", {}).items() if k not in ("namedStyleType", "headingId")}
        text = e.text.rstrip("\n")
        if e.kind == "same":
            new_runs = runs
        elif e.kind == "skills":
            label = text[: text.index(": ") + 2]
            value = text[len(label):]
            label_runs, acc = [], 0
            for t, s in runs:
                take = t[: max(0, len(label) - acc)]
                if take:
                    label_runs.append((take, s))
                acc += len(t)
            new_runs = label_runs + [(value, _dominant([(t, s) for t, s in runs][-1:]))]
        else:
            new_runs = [(text, _dominant(runs))]
        specs.append(para("", src.named_style, src.list_id, src.nesting or None, runs=new_runs, pstyle=ps))
    return doc(*specs, revision=revision, doc_id=before_doc["documentId"])
