import copy
import json

import pytest

from cvtailor.facts import FactsError, check_facts, load_facts, numbers_in
from cvtailor.parse import parse_resume


def fact(fid, claim, metrics=(), used_in=(), skills=("Python",), role="acme-sdet", verified=True, notes=""):
    return {
        "id": fid, "role_id": role, "type": "achievement", "claim": claim,
        "metrics": [{"value": v, "meaning": "m"} for v in metrics],
        "skills": list(skills), "tags": ["t"], "used_in": [{"resume_id": r, "quote": q} for r, q in used_in],
        "sources": ["master_cv"], "confidence": "stated", "verified": verified, "notes": notes,
    }


def facts_data():
    return {
        "schema_version": 1,
        "roles": [{"id": "acme-sdet", "employer": "Acme", "employer_description": "", "title": "Senior SDET",
                   "start": "2025-10", "end": None, "project": None, "is_current": True}],
        "facts": [
            fact("f-001", "Built plugin one.", used_in=[("cv", "Built plugin one.")]),
            fact("f-002", "Built plugin two and three.", used_in=[("cv", "Built plugin two."), ("cv", "Built plugin three.")]),
            fact("f-003", "Own the QA platform used by three teams.", used_in=[("cv", "Own the QA platform used by three teams.")]),
            fact("f-004", "Migrated tests and built API tests.", used_in=[("cv", "Migrated tests."), ("cv", "Built API tests.")]),
        ],
        "skills": [
            {"name": "Python", "aliases": ["py"], "category": "Dev", "recency": "current", "evidence": ["f-001"]},
            {"name": "Git", "aliases": [], "category": "Tools", "recency": "current", "evidence": [], "basic": True},
        ],
        "education": [],
    }


@pytest.fixture
def resumes(resume_doc):
    return {"cv": parse_resume(resume_doc, ["acme"])}


def check(data, resumes):
    return check_facts(load_facts(copy.deepcopy(data)), resumes)


def test_numbers_in():
    assert numbers_in("from 42% to 17% across 120+ cases, 2.5M runs and 2 350K, ~10 minutes.") == [
        "42%", "17%", "120+", "2.5M", "2", "350K", "10"
    ]


def test_clean_data_has_no_problems(resumes):
    report = check(facts_data(), resumes)
    assert report.problems == []
    assert report.stats["facts"] == 4 and report.stats["verified"] == 4


def test_load_facts_rejects_bad_schema(tmp_path):
    data = facts_data()
    del data["facts"][0]["claim"]
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(data))
    with pytest.raises(FactsError, match="f-001|claim"):
        load_facts(path)


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda d: d["facts"].append(fact("f-001", "Dup.")), "duplicate"),
        (lambda d: d["facts"][0].update(role_id="nope"), "unknown role"),
        (lambda d: d["skills"][0]["evidence"].append("f-999"), "f-999"),
        (lambda d: d["facts"][0]["skills"].append("Rust"), "Rust"),
        (lambda d: d["facts"][0].update(claim="Built 9 plugins."), "9"),
        (lambda d: d["facts"][0]["used_in"].append({"resume_id": "other", "quote": "x"}), "unknown resume"),
        (lambda d: d["facts"][0]["used_in"][0].update(quote="Not in the resume."), "quote not found"),
        (lambda d: d["skills"].append({"name": "Docker", "aliases": [], "category": "T", "recency": "current", "evidence": []}), "Docker"),
        (lambda d: d["facts"][0].update(notes="Conflict: a vs b"), "unresolved"),
    ],
)
def test_problems_detected(resumes, mutate, needle):
    data = facts_data()
    mutate(data)
    report = check(data, resumes)
    assert any(needle in p for p in report.problems), report.problems


def test_alias_counts_as_skill(resumes):
    data = facts_data()
    data["facts"][0]["skills"] = ["py"]
    assert check(data, resumes).problems == []


def test_resume_number_must_be_backed_by_covering_fact(resume_doc):
    resume_doc = copy.deepcopy(resume_doc)
    from conftest import resume_elements
    from docbuilder import doc, para

    els = [para("Built plugin one for 3 teams.", list_id="L1") if "".join(t for t, _ in e["runs"]) == "Built plugin one." else e
           for e in resume_elements()]
    resumes = {"cv": parse_resume(doc(*els), ["acme"])}
    data = facts_data()
    data["facts"][0]["used_in"][0]["quote"] = "Built plugin one"
    report = check(data, resumes)
    assert any("'3'" in p and "exp.acme.senior-sdet.b01" in p for p in report.problems), report.problems
    data["facts"][0]["metrics"] = [{"value": "3 teams", "meaning": "teams"}]
    data["facts"][0]["claim"] = "Built plugin one for 3 teams."
    assert check(data, resumes).problems == []


def test_uncovered_editable_bullets_are_warnings(resumes):
    data = facts_data()
    data["facts"] = data["facts"][:3]
    report = check(data, resumes)
    assert report.problems == []
    assert any("exp.acme.qa-engineer.b01" in w for w in report.warnings)
    assert not any("summary" in w for w in report.warnings)


def test_unverified_facts_are_warnings(resumes):
    data = facts_data()
    data["facts"][1]["verified"] = False
    report = check(data, resumes)
    assert report.problems == [] and report.stats["verified"] == 3
    assert any("f-002" in w for w in report.warnings)


def test_check_without_resumes_skips_quote_checks():
    data = facts_data()
    data["facts"][0]["used_in"][0]["quote"] = "anything"
    report = check_facts(load_facts(data), None)
    assert report.problems == []
