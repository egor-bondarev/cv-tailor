import json

import pytest

from cvtailor.checks import (
    check_analysis, check_route, check_vacancy, load_ai_json, parse_json_text, parse_plan_ops,
)
from cvtailor.facts import load_facts
from cvtailor.parse import parse_resume
from cvtailor.schemas import AiOp, AiPlan, Analysis, Review, Route, Vacancy
from test_facts_index import data_with_roles

VAC = {"title": "SDET", "company": "X", "seniority": "senior", "language": "en", "summary": "s",
       "must_have": ["Python"], "nice_to_have": [], "responsibilities": [], "skills": ["k8s", "python"], "domain": None}


@pytest.fixture
def facts():
    return load_facts(data_with_roles())


@pytest.fixture
def resume(resume_doc):
    return parse_resume(resume_doc, ["acme"])


def test_parse_json_text_fenced_nested_last_valid():
    text = 'thinking... {"op": 1}\n```json\n{"verdicts": [{"op": 1, "verdict": "supported"}]}\n```\ndone'
    review, errors = parse_json_text(text, Review)
    assert errors == [] and review.verdicts[0].op == 1


def test_parse_json_text_garbage():
    review, errors = parse_json_text("no json here", Review)
    assert review is None and errors[0].rule == "schema"


def test_load_ai_json_missing_empty_garbage(tmp_path):
    p = tmp_path / "x.json"
    assert load_ai_json(p, Vacancy)[1][0].rule == "missing"
    p.write_text("  ")
    assert load_ai_json(p, Vacancy)[1][0].rule == "empty"
    p.write_text("{oops")
    assert load_ai_json(p, Vacancy)[1][0].rule == "schema"
    p.write_text(json.dumps(VAC))
    v, errs = load_ai_json(p, Vacancy)
    assert errs == [] and v.title == "SDET"


def test_vacancy_normalizes_skills(facts):
    v, errs = check_vacancy(Vacancy(**VAC), facts)
    assert errs == [] and v.skills == ["Kubernetes", "Python"]


def test_vacancy_requires_must_have():
    with pytest.raises(ValueError):
        Vacancy(**{**VAC, "must_have": []})


def test_route_checks():
    ok = Route(choice="a", confidence="high", ranking=["a", "b"], reason="r")
    assert check_route(ok, ["a", "b"]) == []
    assert check_route(Route(choice="z", confidence="high", ranking=["z", "a"], reason=""), ["a", "b"])
    assert check_route(Route(choice="a", confidence="high", ranking=["b", "a"], reason=""), ["a", "b"])
    assert check_route(Route(choice="a", confidence="high", ranking=["a"], reason=""), ["a", "b"])
    assert check_route(Route(choice="a", confidence="high", ranking=["a"], reason=""), ["a"]) == []


def _analysis(resume, **over):
    editable = [b.id for b in resume.blocks if b.editable and b.kind in ("bullet", "intro")]
    base = {
        "requirements": [{"text": "Python", "kind": "must", "status": "covered", "fact_ids": ["f-001"], "block_ids": []},
                         {"text": "Go", "kind": "nice", "status": "gap"}],
        "relevance": [{"block_id": b, "score": 2, "reason": ""} for b in editable],
        "candidate_facts": ["f-001", "f-002"],
    }
    base.update(over)
    return Analysis(**base)


def test_analysis_ok(resume, facts):
    assert check_analysis(_analysis(resume), resume, facts) == []


def test_analysis_unknown_ids(resume, facts):
    a = _analysis(resume, candidate_facts=["f-999", "f-006"])
    a.requirements[0].block_ids = ["nope"]
    errs = check_analysis(a, resume, facts)
    details = " ".join(e.detail for e in errs)
    assert "f-999" in details and "f-006" in details and "nope" in details


def test_analysis_missing_relevance(resume, facts):
    a = _analysis(resume)
    a.relevance = a.relevance[1:]
    assert any(e.rule == "relevance" for e in check_analysis(a, resume, facts))
    a = _analysis(resume)
    a.relevance.append(a.relevance[0])
    assert any(e.rule == "relevance" for e in check_analysis(a, resume, facts))


def test_analysis_status_without_refs(resume, facts):
    a = _analysis(resume)
    a.requirements[0].fact_ids = []
    assert any(e.rule == "requirement" for e in check_analysis(a, resume, facts))


def test_analysis_score_range():
    with pytest.raises(ValueError):
        Analysis(requirements=[], relevance=[{"block_id": "b", "score": 4, "reason": ""}], candidate_facts=[])


def test_parse_plan_ops_keeps_good_ops():
    raw = AiPlan(ops=[
        {"id": 1, "op": "replace", "block": "summary", "new_text": "x", "evidence": ["f-001"]},
        {"id": 2, "op": "replace", "block": "summary"},
        {"id": 1, "op": "delete", "block": "b"},
        {"op": "delete", "block": "c", "colour": "red"},
    ])
    ops, errs = parse_plan_ops(raw)
    assert [o.id for o in ops] == [1]
    assert sorted({str(e.op) for e in errs}) == ["1", "2", "None"]


def test_ai_op_forbids_extra_fields():
    with pytest.raises(ValueError):
        AiOp(id=1, op="delete", block="b", colour="red")
