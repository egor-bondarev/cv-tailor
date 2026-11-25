import pytest

from cvtailor.docmodel import (
    DocFormatError,
    body_content,
    dominant_style,
    has_suggestions,
    load_doc,
    norm_style,
    paragraphs,
    snapshot,
    styles_in_range,
    tables,
    utf16_len,
)
from docbuilder import doc, para, table

BOLD = {"bold": True, "fontSize": {"magnitude": 10, "unit": "PT"}}
PLAIN = {"fontSize": {"magnitude": 10, "unit": "PT"}}


def test_load_doc_accepts_wrapped_tabs_and_bare():
    bare = doc(para("Hello"))
    tabbed = {k: v for k, v in bare.items() if k != "body"}
    tabbed["tabs"] = [{"documentTab": {"body": bare["body"]}}]
    assert body_content(load_doc({"content": tabbed})) == body_content(load_doc(bare))


def test_load_doc_revision_optional():
    d = doc(para("x"), revision=None)
    assert load_doc(d)["documentId"] == "doc-1"
    with pytest.raises(DocFormatError):
        load_doc(d, require_revision=True)


def test_load_doc_rejects_missing_body():
    with pytest.raises(DocFormatError):
        load_doc({"documentId": "d", "revisionId": "r"})


def test_utf16_len():
    assert utf16_len("abc") == 3
    assert utf16_len("😀") == 2
    assert utf16_len("—") == 1


def test_paragraph_indices_from_builder():
    ps = paragraphs(doc(para("Ab"), para("😀x")))
    assert (ps[0].start, ps[0].end) == (1, 4)
    assert (ps[1].start, ps[1].end) == (4, 8)
    assert ps[1].text == "😀x\n"
    assert ps[1].body_text == "😀x"


def test_tables_listed_and_skipped_by_paragraphs():
    d = doc(para("a"), table(["x", "y"]), para("b"))
    ps = paragraphs(d)
    ts = tables(d)
    assert [p.body_text for p in ps] == ["a", "b"]
    assert len(ts) == 1 and ts[0].text == "xy"
    assert ps[1].start == ts[0].end


def test_list_nesting_default_zero():
    ps = paragraphs(doc(para("item", list_id="L1"), para("plain")))
    assert ps[0].list_id == "L1" and ps[0].nesting == 0
    assert ps[1].list_id is None and ps[1].nesting is None


def test_norm_style_equivalences():
    base = norm_style({})
    assert norm_style({"bold": False}) == base
    assert norm_style({"foregroundColor": {"color": {"rgbColor": {}}}}) == base
    assert norm_style({"backgroundColor": {}}) == base
    assert norm_style({"baselineOffset": "NONE"}) == base
    assert norm_style({"bold": True}) != base


def test_snapshot_style_runs_keep_lengths():
    p = paragraphs(doc(para("", runs=[("Dev: ", BOLD), ("Py", PLAIN), ("thon", PLAIN)])))[0]
    snap = snapshot(p)
    b, pl = norm_style(BOLD), norm_style(PLAIN)
    assert snap.style_runs == [(5, b), (6, pl)]
    assert styles_in_range(snap, 0, 5) == [(5, b)]
    assert styles_in_range(snap, 3, 7) == [(2, b), (2, pl)]
    assert dominant_style(snap.style_runs) == pl


def test_has_suggestions_finds_style_and_text():
    clean = doc(para("a"))
    assert has_suggestions(clean) == []
    dirty = doc(para("a"))
    run = dirty["body"]["content"][1]["paragraph"]["elements"][0]["textRun"]
    run["suggestedTextStyleChanges"] = {"s1": {"textStyle": {"bold": True}}}
    assert has_suggestions(dirty)
