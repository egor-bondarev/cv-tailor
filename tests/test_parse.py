import pytest

from conftest import resume_elements
from cvtailor.docmodel import utf16_len
from cvtailor.models import ParseError
from cvtailor.naming import slug
from cvtailor.parse import parse_resume
from docbuilder import doc, para, table


def _text(e):
    return "".join(t for t, _ in e["runs"])


def _without(elements, *texts):
    return [e for e in elements if _text(e) not in texts]


def test_slug():
    assert slug("Initech / Globex Holdings") == "initech-globex-holdings"
    assert slug("Staff QA - Release & Tooling Team") == "staff-qa-release-tooling-team"
    assert slug("Яндекс") == "яндекс"
    assert slug("!!!") == "x"


def test_ids_and_zones(resume_doc):
    r = parse_resume(resume_doc, ["Acme"])
    ids = {b.id for b in r.blocks}
    expected = {
        "name", "contact.01", "contact.02", "title", "summary", "skills.development", "skills.testing",
        "exp.acme.desc01", "exp.acme.senior-sdet.intro",
        "exp.acme.senior-sdet.b01", "exp.acme.senior-sdet.b02", "exp.acme.senior-sdet.b03",
        "exp.acme.qa-engineer.b01", "exp.acme.qa-engineer.b02",
        "exp.globex.qa.b01", "early.initech.b01", "ro.education.01",
    }
    assert expected <= ids
    editable = {b.id for b in r.blocks if b.editable}
    assert editable == {
        "title", "summary", "skills.development", "skills.testing", "exp.acme.senior-sdet.intro",
        "exp.acme.senior-sdet.b01", "exp.acme.senior-sdet.b02", "exp.acme.senior-sdet.b03",
        "exp.acme.qa-engineer.b01", "exp.acme.qa-engineer.b02",
    }
    assert r.get("exp.globex.qa.b01").kind == "bullet"
    assert r.revision_id == "rev-1" and r.document_id == "doc-1"


def test_every_nonempty_element_has_block(resume_doc):
    r = parse_resume(resume_doc, ["acme"])
    assert len(r.blocks) == len(resume_elements())


def test_skills_label_len(resume_doc):
    assert parse_resume(resume_doc, ["acme"]).get("skills.development").label_len == 13


def test_block_indices_utf16():
    els = resume_elements()
    i = next(k for k, e in enumerate(els) if e["runs"][0][0] == "Built plugin one.")
    els[i] = para("😀 done", list_id="L1")
    b = parse_resume(doc(*els), ["acme"]).get("exp.acme.senior-sdet.b01")
    assert b.end - b.start == utf16_len("😀 done") + 1
    assert b.text == "😀 done"


def test_missing_section_raises():
    els = _without(resume_elements(), "TECHNICAL SKILLS", "Development: Python", "Testing: pytest")
    with pytest.raises(ParseError, match="TECHNICAL SKILLS"):
        parse_resume(doc(*els), ["acme"])


def test_two_summary_paragraphs_raise():
    els = resume_elements()
    i = next(k for k, e in enumerate(els) if e["runs"][0][0] == "SUMMARY")
    els.insert(i + 1, para("Another summary paragraph."))
    with pytest.raises(ParseError, match="SUMMARY"):
        parse_resume(doc(*els), ["acme"])


def test_skills_line_without_colon_raises():
    els = resume_elements()
    i = next(k for k, e in enumerate(els) if e["runs"][0][0] == "Testing: pytest")
    els[i] = para("Testing pytest")
    with pytest.raises(ParseError, match="Testing pytest"):
        parse_resume(doc(*els), ["acme"])


def test_rejects_doc_with_pending_suggestions(resume_doc):
    run = resume_doc["body"]["content"][3]["paragraph"]["elements"][0]["textRun"]
    run["suggestedDeletionIds"] = ["s1"]
    with pytest.raises(ParseError, match="suggestions"):
        parse_resume(resume_doc, ["acme"])


def test_tolerates_messy_layout():
    els = resume_elements()
    els = [para("  summary ", "HEADING_1") if e["runs"][0][0] == "SUMMARY" else e for e in els]
    i = next(k for k, e in enumerate(els) if e["runs"][0][0] == "Built plugin two.")
    els[i] = para("Built plugin\x0btwo.", list_id="L1")
    els.insert(i + 1, para("Sub point.", list_id="L1", nesting=1))
    els.insert(i, para(""))
    j = next(k for k, e in enumerate(els) if e["runs"][0][0] == "QA Engineer | Jul 2024 - Oct 2025")
    els.insert(j, para("Stack: Python"))
    els.append(table(["Cell A", "Cell B"]))
    r = parse_resume(doc(*els), ["acme"])
    ids = [b.id for b in r.blocks]
    for k in ("b01", "b02", "b03"):
        assert f"exp.acme.senior-sdet.{k}" in ids
    assert "\x0b" in r.get("exp.acme.senior-sdet.b02").text
    for ro in ("table.01", "exp.acme.senior-sdet.p01", "exp.acme.senior-sdet.s01"):
        assert not r.get(ro).editable
    assert r.get("table.01").text == "Cell ACell B"
    nonempty = sum(1 for e in els if e["kind"] == "table" or "".join(t for t, _ in e["runs"]).strip())
    assert len(r.blocks) == nonempty
    assert "exp.acme.senior-sdet.b04" not in ids and r.get("exp.acme.senior-sdet.b02").has_children


def test_duplicate_slugs_get_suffix():
    els = resume_elements()
    j = next(k for k, e in enumerate(els) if e["runs"][0][0] == "QA Engineer | Jul 2024 - Oct 2025")
    els[j] = para("Senior SDET | Jul 2024 - Oct 2025", "HEADING_3")
    k = next(i for i, e in enumerate(els) if e["runs"][0][0] == "Testing: pytest")
    els[k] = para("Development: Go")
    r = parse_resume(doc(*els), ["acme"])
    ids = {b.id for b in r.blocks}
    assert "exp.acme.senior-sdet-2.b01" in ids
    assert {"skills.development", "skills.development-2"} <= ids


def test_role_bullets(resume_doc):
    r = parse_resume(resume_doc, ["acme"])
    assert [b.text for b in r.role_bullets("acme", "senior-sdet")] == [
        "Built plugin one.", "Built plugin two.", "Built plugin three.",
    ]


def test_get_unknown_block_raises(resume_doc):
    with pytest.raises(KeyError, match="nope"):
        parse_resume(resume_doc, ["acme"]).get("nope")


def _nested_doc(extra_after_b02=()):
    els = resume_elements()
    i = next(k for k, e in enumerate(els) if _text(e) == "Built plugin two.")
    els.insert(i + 1, para("Sub point.", list_id="L1", nesting=1))
    return els


def test_nested_bullet_ids_do_not_depend_on_parent_number():
    r = parse_resume(doc(*_nested_doc()), ["acme"])
    sub = [b for b in r.blocks if b.text == "Sub point."][0]
    assert sub.id == "exp.acme.senior-sdet.s01" and not sub.editable


def test_second_subtitle_raises():
    els = resume_elements()
    els.insert(2, para("Another subtitle", "SUBTITLE"))
    with pytest.raises(ParseError, match="SUBTITLE"):
        parse_resume(doc(*els), ["acme"])


def test_second_title_raises():
    els = resume_elements()
    els.insert(1, para("Other Name", "TITLE"))
    with pytest.raises(ParseError, match="TITLE"):
        parse_resume(doc(*els), ["acme"])


def test_boundary_flag_for_last_paragraph_and_before_table():
    els = resume_elements()
    i = next(k for k, e in enumerate(els) if _text(e) == "Built API tests.")
    els.insert(i + 1, table(["T"]))
    r = parse_resume(doc(*els), ["acme"])
    assert r.get("exp.acme.qa-engineer.b02").at_boundary
    assert r.get("ro.education.01").at_boundary
    assert not r.get("exp.acme.qa-engineer.b01").at_boundary
