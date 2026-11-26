from conftest import resume_elements
from cvtailor.checks import CheckError
from cvtailor.models import Op, VerifyReport
from cvtailor.parse import parse_resume
from cvtailor.report import ReportData, acceptance, review_md, summary_txt
from cvtailor.schemas import Analysis, Review, Route, Vacancy
from docbuilder import doc, para
from test_checks import VAC
from test_validate import B1, B2, B3, facts_v

OPS = [
    Op(id=1, op="replace", block=B1, new_text="New one.", evidence=["f-001"], reason="must_have"),
    Op(id=2, op="insert_after", after=B2, new_text="Inserted.", evidence=["f-010"]),
    Op(id=3, op="delete", block=B3),
    Op(id=4, op="replace_skills", block="skills.development", new_value="Python, Go"),
]


def data(**over):
    resume = parse_resume(doc(*resume_elements()), ["acme"])
    base = dict(
        vacancy=Vacancy(**VAC), resume_label="Senior SDET", route=Route(choice="cv", confidence="high", ranking=["cv"], reason=""),
        doc_url="https://docs.google.com/document/d/x/edit",
        analysis=Analysis(requirements=[{"text": "Kotlin", "kind": "must", "status": "gap"}],
                          relevance=[{"block_id": B1, "score": 3, "reason": ""}], candidate_facts=[]),
        applied=OPS[:3], dropped=[(OPS[3], [CheckError(rule="skills", detail="'Go' is a previous skill", op=4)])],
        resume=resume, facts=facts_v(),
        review=Review(verdicts=[{"op": 1, "verdict": "supported"}, {"op": 2, "verdict": "partial", "quote": "Inserted", "comment": "too broad"}]),
        reviewer_status="codex", verify=VerifyReport(ok=True, problems=[]),
    )
    base.update(over)
    return ReportData(**base)


def test_review_md_sections():
    md = review_md(data())
    for needle in ("Senior SDET", "https://docs.google.com", "Kotlin", "Built plugin one.", "New one.",
                   "f-001", "relevance 3", "supported", "partial", "Inserted."):
        assert needle in md, needle


def test_review_md_lists_dropped_with_rules():
    md = review_md(data())
    assert "Not applied" in md and "skills" in md and "previous skill" in md


def test_summary_flags_partial_and_unsupported():
    s = summary_txt(data())
    assert "3 edits applied, 1 dropped" in s and "op 2" in s and "partial" in s and "Kotlin" in s
    assert len(s.strip().splitlines()) <= 8


def test_summary_mentions_reviewer_none():
    assert "reviewer: none: not configured" in summary_txt(data(review=None, reviewer_status="none: not configured"))


def test_summary_verify_failure():
    s = summary_txt(data(verify=VerifyReport(ok=False, problems=["text differs"])))
    assert "FAILED" in s and "text differs" in s


def _final(elements):
    return parse_resume(doc(*elements, revision="rev-2"), ["acme"])


def _t(e):
    return "".join(t for t, _ in e["runs"])


def test_acceptance_outcomes():
    before = parse_resume(doc(*resume_elements()), ["acme"])
    ops = OPS[:3]
    accepted = []
    for e in resume_elements():
        if _t(e) == "Built plugin one.":
            accepted.append(para("New one.", list_id="L1"))
        elif _t(e) == "Built plugin two.":
            accepted += [e, para("Inserted.", list_id="L1")]
        elif _t(e) == "Built plugin three.":
            continue
        else:
            accepted.append(e)
    out = {o.op: o.outcome for o in acceptance(before, _final(accepted), ops)}
    assert out == {1: "accepted", 2: "accepted", 3: "accepted"}
    rejected = {o.op: o.outcome for o in acceptance(before, _final(resume_elements()), ops)}
    assert rejected == {1: "rejected", 2: "rejected", 3: "rejected"}
    edited_els = [para("New one, tweaked.", list_id="L1") if _t(e) == "New one." else
                  para("Inserted, tweaked.", list_id="L1") if _t(e) == "Inserted." else e for e in accepted]
    edited = {o.op: o.outcome for o in acceptance(before, _final(edited_els), ops)}
    assert edited == {1: "edited", 2: "edited", 3: "accepted"}
