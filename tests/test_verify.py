import pytest

from conftest import BOLD, PLAIN, resume_elements
from cvtailor.models import Op
from cvtailor.parse import parse_resume
from cvtailor.verify import expected_texts, final_check, verify_applied
from docbuilder import doc, para, table

B1 = "exp.acme.senior-sdet.b01"
B2 = "exp.acme.senior-sdet.b02"
B3 = "exp.acme.senior-sdet.b03"
LINK = {**PLAIN, "link": {"url": "https://example.com"}}

OPS = [
    Op(id=1, op="replace", block=B1, new_text="New one."),
    Op(id=2, op="replace_skills", block="skills.development", new_value="Go"),
    Op(id=3, op="insert_after", after=B2, new_text="Inserted."),
    Op(id=4, op="delete", block=B3),
]


def _t(e):
    return "".join(t for t, _ in e["runs"])


def applied_elements(new_one=None, skills=None, inserted=None, extra=None):
    """Elements as Google would return them with all OPS accepted."""
    out = []
    for e in resume_elements():
        text = _t(e)
        if text == "Built plugin one.":
            out.append(new_one or para("New one.", list_id="L1"))
        elif text == "Development: Python":
            out.append(skills or para("", runs=[("Development: ", BOLD), ("Go", PLAIN)]))
        elif text == "Built plugin two.":
            out.append(e)
            out.append(inserted or para("Inserted.", list_id="L1"))
        elif text == "Built plugin three.":
            continue
        else:
            out.append(e)
    return out + (extra or [])


@pytest.fixture
def before():
    return doc(*resume_elements())


@pytest.fixture
def resume(before):
    return parse_resume(before, ["acme"])


def test_expected_texts_all_ops(before, resume):
    texts = expected_texts(before, resume, OPS)
    assert texts == [_t(e) + "\n" for e in applied_elements()]


def test_verify_ok_on_correct_preview(before, resume):
    report = verify_applied(before, doc(*applied_elements()), resume, OPS)
    assert report.ok is True and report.problems == []


def test_verify_reports_text_mismatch(before, resume):
    report = verify_applied(before, doc(*applied_elements(new_one=para("New onee.", list_id="L1"))), resume, OPS)
    assert not report.ok and "text" in report.problems[0]


def test_verify_reports_untouched_style_change(before, resume):
    els = applied_elements()
    els = [para("Migrated tests.", list_id="L2", runs=[("Migrated tests.", BOLD)]) if _t(e) == "Migrated tests." else e for e in els]
    report = verify_applied(before, doc(*els), resume, OPS)
    assert not report.ok and any("Migrated tests." in p for p in report.problems)


def test_verify_inserted_bullet_wrong_list(before, resume):
    report = verify_applied(before, doc(*applied_elements(inserted=para("Inserted.", list_id="OTHER"))), resume, OPS)
    assert not report.ok and any("Inserted." in p for p in report.problems)


def test_verify_detects_link_spread():
    els = [para("", list_id="L1", runs=[("Built ", PLAIN), ("plugin", LINK), (" one.", PLAIN)]) if _t(e) == "Built plugin one." else e for e in resume_elements()]
    before = doc(*els)
    resume = parse_resume(before, ["acme"])
    ops = [Op(id=1, op="replace", block=B1, new_text="New one.")]
    good = [para("New one.", list_id="L1") if _t(e) == "Built plugin one." else e for e in els]
    bad = [para("", list_id="L1", runs=[("New one.", LINK)]) if _t(e) == "Built plugin one." else e for e in els]
    assert verify_applied(before, doc(*good), resume, ops).ok
    report = verify_applied(before, doc(*bad), resume, ops)
    assert not report.ok and any("New one." in p for p in report.problems)


def test_verify_skills_label_style_kept(before, resume):
    bad = applied_elements(skills=para("", runs=[("Development: ", BOLD), ("Go", BOLD)]))
    report = verify_applied(before, doc(*bad), resume, OPS)
    assert not report.ok and any("Development" in p for p in report.problems)
    lost_label = applied_elements(skills=para("", runs=[("Development: ", PLAIN), ("Go", PLAIN)]))
    assert not verify_applied(before, doc(*lost_label), resume, OPS).ok


def test_verify_bold_false_equals_missing(before, resume):
    explicit = para("New one.", list_id="L1", runs=[("New one.", {**PLAIN, "bold": False})])
    assert verify_applied(before, doc(*applied_elements(new_one=explicit)), resume, OPS).ok


def test_verify_table_change_detected():
    before = doc(*resume_elements(), table(["A", "B"]))
    resume = parse_resume(before, ["acme"])
    report = verify_applied(before, doc(*applied_elements(extra=[table(["A", "C"])])), resume, OPS)
    assert not report.ok and any("table" in p for p in report.problems)


def test_final_ok_after_accept_all(before, resume):
    assert final_check(before, doc(*applied_elements(), revision="rev-2"), resume, ["acme"]).ok


def test_final_ok_after_reject_all(before, resume):
    assert final_check(before, doc(*resume_elements(), revision="rev-2"), resume, ["acme"]).ok


def test_final_detects_text_suggestion(before, resume):
    final = doc(*applied_elements())
    final["body"]["content"][2]["paragraph"]["elements"][0]["textRun"]["suggestedInsertionIds"] = ["s1"]
    report = final_check(before, final, resume, ["acme"])
    assert not report.ok and "unresolved suggestions" in report.problems[0]


def test_final_detects_style_suggestion(before, resume):
    final = doc(*applied_elements())
    final["body"]["content"][2]["paragraph"]["elements"][0]["textRun"]["suggestedTextStyleChanges"] = {"s1": {}}
    assert not final_check(before, final, resume, ["acme"]).ok


def test_final_detects_readonly_change(before, resume):
    els = [para("University of Elsewhere | 2010") if _t(e).startswith("University") else e for e in applied_elements()]
    report = final_check(before, doc(*els), resume, ["acme"])
    assert not report.ok and any("ro.education.01" in p for p in report.problems)


def test_final_ok_with_user_edit_in_editable_bullet(before, resume):
    edited = para("", list_id="L1", runs=[("Rewritten by ", PLAIN), ("me", BOLD)])
    assert final_check(before, doc(*applied_elements(new_one=edited)), resume, ["acme"]).ok


def test_final_detects_bullet_moved_to_other_list(before, resume):
    report = final_check(before, doc(*applied_elements(new_one=para("New one.", list_id="ZZ"))), resume, ["acme"])
    assert not report.ok and any("list" in p for p in report.problems)


def test_final_parse_error_is_problem(before, resume):
    els = applied_elements()
    i = next(k for k, e in enumerate(els) if _t(e) == "SUMMARY")
    els.insert(i + 2, para("Second summary paragraph."))
    report = final_check(before, doc(*els), resume, ["acme"])
    assert not report.ok and "cannot parse" in report.problems[0]


def test_final_detects_added_readonly_content(before, resume):
    els = applied_elements()
    i = next(k for k, e in enumerate(els) if _t(e) == "Refactored NUnit tests.")
    els.insert(i + 1, para("Extra readonly bullet.", list_id="L3"))
    report = final_check(before, doc(*els), resume, ["acme"])
    assert not report.ok and any("added" in p for p in report.problems)


def test_final_ok_with_nested_bullet_after_insert_and_delete():
    els = resume_elements()
    i = next(k for k, e in enumerate(els) if _t(e) == "Built plugin two.")
    els.insert(i + 1, para("Sub point.", list_id="L1", nesting=1))
    before = doc(*els)
    resume = parse_resume(before, ["acme"])
    after = [e for e in els if _t(e) != "Built plugin one."]
    j = next(k for k, e in enumerate(after) if _t(e) == "Built plugin three.")
    after.insert(j + 1, para("Inserted.", list_id="L1"))
    assert final_check(before, doc(*after), resume, ["acme"]).ok
