import pytest

from conftest import resume_elements
from cvtailor.docmodel import utf16_len
from cvtailor.models import BuildError, Op
from cvtailor.parse import parse_resume
from cvtailor.requests import build_requests
from docbuilder import doc, para

ONLY_ACME = {"acme": 1}  # older companies stay read-only in these tests

B1 = "exp.acme.senior-sdet.b01"
B2 = "exp.acme.senior-sdet.b02"
B3 = "exp.acme.senior-sdet.b03"


@pytest.fixture
def resume(resume_doc):
    return parse_resume(resume_doc, ONLY_ACME)


def _first_index(req: dict) -> int:
    body = next(iter(req.values()))
    return body["range"]["startIndex"] if "range" in body else body["location"]["index"]


def test_replace_bullet_requests(resume):
    b = resume.get(B2)
    body = build_requests(resume, [Op(id=1, op="replace", block=B2, new_text="New")])
    assert body["requests"] == [
        {"deleteContentRange": {"range": {"startIndex": b.start, "endIndex": b.end - 1}}},
        {"insertText": {"location": {"index": b.start}, "text": "New"}},
    ]


def test_replace_skills_keeps_label(resume):
    b = resume.get("skills.development")
    body = build_requests(resume, [Op(id=1, op="replace_skills", block="skills.development", new_value="Go")])
    assert body["requests"][0]["deleteContentRange"]["range"] == {"startIndex": b.start + 13, "endIndex": b.end - 1}
    assert body["requests"][1]["insertText"] == {"location": {"index": b.start + 13}, "text": "Go"}


def test_delete_bullet_range(resume):
    b = resume.get(B3)
    body = build_requests(resume, [Op(id=1, op="delete", block=B3)])
    assert body["requests"] == [{"deleteContentRange": {"range": {"startIndex": b.start, "endIndex": b.end}}}]


def test_write_control(resume):
    body = build_requests(resume, [Op(id=1, op="delete", block=B3)])
    assert body["writeControl"] == {"requiredRevisionId": "rev-1", "writeMode": "SUGGEST"}
    assert build_requests(resume, [Op(id=1, op="delete", block=B3)], mode="EDIT")["writeControl"]["writeMode"] == "EDIT"


def test_requests_sorted_descending(resume):
    ops = [
        Op(id=1, op="replace", block="summary", new_text="S"),
        Op(id=2, op="replace", block=B3, new_text="T"),
        Op(id=3, op="replace", block=B1, new_text="U"),
    ]
    reqs = build_requests(resume, ops)["requests"]
    starts = [_first_index(r) for r in reqs if "deleteContentRange" in r]
    assert starts == sorted(starts, reverse=True)
    assert starts == [resume.get(B3).start, resume.get(B1).start, resume.get("summary").start]


def test_multiple_inserts_same_anchor_with_anchor_replaced(resume):
    b = resume.get(B1)
    ops = [
        Op(id=5, op="insert_after", after=B1, new_text="B"),
        Op(id=3, op="insert_after", after=B1, new_text="A"),
        Op(id=1, op="replace", block=B1, new_text="New"),
    ]
    reqs = build_requests(resume, ops)["requests"]
    assert reqs[0] == {"insertText": {"location": {"index": b.end - 1}, "text": "\nA\nB"}}
    assert reqs[1] == {"deleteContentRange": {"range": {"startIndex": b.start, "endIndex": b.end - 1}}}
    assert reqs[2] == {"insertText": {"location": {"index": b.start}, "text": "New"}}


def test_rejects_insert_after_deleted_anchor(resume):
    ops = [Op(id=1, op="insert_after", after=B1, new_text="A"), Op(id=2, op="delete", block=B1)]
    with pytest.raises(BuildError, match="anchor"):
        build_requests(resume, ops)


def test_utf16_offsets_after_emoji():
    els = [para("Dev 😀: Python") if "".join(t for t, _ in e["runs"]) == "Development: Python" else e for e in resume_elements()]
    r = parse_resume(doc(*els), ONLY_ACME)
    b = r.get("skills.dev")
    reqs = build_requests(r, [Op(id=1, op="replace_skills", block="skills.dev", new_value="Go")])["requests"]
    assert reqs[0]["deleteContentRange"]["range"]["startIndex"] == b.start + utf16_len("Dev 😀: ")


def test_replace_of_bullet_with_soft_break_allowed():
    els = [para("Built\x0bplugin one.", list_id="L1") if "".join(t for t, _ in e["runs"]) == "Built plugin one." else e for e in resume_elements()]
    r = parse_resume(doc(*els), ONLY_ACME)
    build_requests(r, [Op(id=1, op="replace", block=B1, new_text="Plain")])


@pytest.mark.parametrize(
    "ops, match",
    [
        ([Op(id=1, op="replace", block="ro.education.01", new_text="X")], "ro.education.01"),
        ([Op(id=1, op="replace", block="exp.globex.qa.b01", new_text="X")], "exp.globex.qa.b01"),
        ([Op(id=1, op="insert_after", after="summary", new_text="X")], "summary"),
        ([Op(id=1, op="replace_skills", block=B1, new_value="X")], B1),
        ([Op(id=1, op="replace", block=B1, new_text="a\nb")], "newline"),
        ([Op(id=1, op="replace", block=B1, new_text="  ")], "empty"),
        ([Op(id=1, op="replace", block=B1, new_text="x"), Op(id=2, op="delete", block=B1)], "more than one"),
        ([Op(id=1, op="delete", block="nope")], "nope"),
    ],
)
def test_rejects_invalid_ops(resume, ops, match):
    with pytest.raises(BuildError, match=match):
        build_requests(resume, ops)


def test_rejects_missing_revision(resume_doc):
    del resume_doc["revisionId"]
    r = parse_resume(resume_doc, ONLY_ACME)
    with pytest.raises(BuildError, match="revision"):
        build_requests(r, [Op(id=1, op="delete", block=B3)])


def test_op_model_requires_fields():
    with pytest.raises(ValueError):
        Op(id=1, op="replace", block=B1)
    with pytest.raises(ValueError):
        Op(id=1, op="insert_after", new_text="x")


def _with_sub():
    els = resume_elements()
    i = next(k for k, e in enumerate(els) if "".join(t for t, _ in e["runs"]) == "Built plugin two.")
    els.insert(i + 1, para("Sub point.", list_id="L1", nesting=1))
    return parse_resume(doc(*els), ONLY_ACME)


def test_rejects_insert_after_bullet_with_children():
    with pytest.raises(BuildError, match="nested"):
        build_requests(_with_sub(), [Op(id=1, op="insert_after", after=B2, new_text="X")])


def test_rejects_delete_of_bullet_with_children():
    with pytest.raises(BuildError, match="nested"):
        build_requests(_with_sub(), [Op(id=1, op="delete", block=B2)])


def test_replace_of_bullet_with_children_allowed():
    build_requests(_with_sub(), [Op(id=1, op="replace", block=B2, new_text="X")])


def test_rejects_delete_of_last_paragraph_in_document():
    drop = {"Globex", "QA | 2019 - 2024", "Refactored NUnit tests.", "EARLIER EXPERIENCE",
            "Initech | Tester | 2015 - 2016", "Tested things.", "EDUCATION", "University of Somewhere | 2010"}
    els = [e for e in resume_elements() if "".join(t for t, _ in e["runs"]) not in drop]
    r = parse_resume(doc(*els), ONLY_ACME)
    with pytest.raises(BuildError, match="last paragraph"):
        build_requests(r, [Op(id=1, op="delete", block="exp.acme.qa-engineer.b02")])
    build_requests(r, [Op(id=1, op="replace", block="exp.acme.qa-engineer.b02", new_text="ok")])
