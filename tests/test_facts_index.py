import copy

import pytest

from cvtailor.facts import RoleMapError, coverage, groups, load_facts, normalize_skills, role_map, verified_facts
from cvtailor.parse import parse_resume
from test_facts import fact, facts_data


def data_with_roles():
    d = facts_data()
    d["roles"].append({"id": "acme-qa", "employer": "Acme", "title": "QA Engineer", "start": "2024-07",
                       "end": "2025-10", "is_current": False})
    d["facts"].append(fact("f-005", "Migrated tests.", role="acme-qa", used_in=[("cv", "Migrated tests.")]))
    d["facts"].append(fact("f-006", "Draft fact.", verified=False, used_in=[("cv", "Built plugin one.")]))
    d["facts"].append(fact("f-007", "Summary fact.", used_in=[("cv", "Senior SDET with 10 years")], metrics=["10"]))
    d["skills"].append({"name": "Kubernetes", "aliases": ["k8s"], "category": "T", "recency": "previous", "evidence": []})
    return d


@pytest.fixture
def resume(resume_doc):
    return parse_resume(resume_doc, ["acme"])


def test_verified_facts():
    assert "f-006" not in verified_facts(load_facts(data_with_roles()))


def test_coverage_excludes_summary_and_unverified(resume):
    cov = coverage(load_facts(data_with_roles()), "cv", resume)
    assert cov["f-002"] == ["exp.acme.senior-sdet.b02", "exp.acme.senior-sdet.b03"]
    assert "f-006" not in cov and "f-007" not in cov


def test_groups_verified_only():
    d = data_with_roles()
    d["facts"].append(fact("f-008", "Also plugin two.", used_in=[("cv", "Built plugin two.")]))
    g = groups(load_facts(d))
    assert ["f-002", "f-008"] in g
    assert all("f-006" not in grp for grp in g)


def _roles(resume, d, overrides=None):
    return role_map(load_facts(d), resume, overrides or {})


def test_role_mapping_exact(resume):
    m = _roles(resume, data_with_roles())
    assert m == {("acme", "senior-sdet"): "acme-sdet", ("acme", "qa-engineer"): "acme-qa"}


def test_role_mapping_shortened_title_and_company(resume):
    d = data_with_roles()
    d["roles"][0].update(employer="Acme Analytics", title="Senior SDET - Platform")
    d["roles"][1].update(employer="Acme Analytics")
    m = _roles(resume, d)
    assert m[("acme", "senior-sdet")] == "acme-sdet"


def test_role_mapping_token_boundary(resume):
    d = data_with_roles()
    for r in d["roles"]:
        r["employer"] = "Acmecorp"
    with pytest.raises(RoleMapError, match="acme"):
        _roles(resume, d)


def test_role_mapping_override_and_ambiguity(resume):
    d = data_with_roles()
    d["roles"].append({"id": "acme-sdet-2", "employer": "Acme", "title": "Senior SDET Lead", "is_current": False})
    d["roles"][0]["title"] = "Senior SDET Staff"
    with pytest.raises(RoleMapError, match="senior-sdet"):
        _roles(resume, d)
    m = _roles(resume, d, {"acme/senior-sdet": "acme-sdet"})
    assert m[("acme", "senior-sdet")] == "acme-sdet"


def test_normalize_skills():
    f = load_facts(data_with_roles())
    assert normalize_skills(["k8s", "PYTHON", "Rust"], f) == ["Kubernetes", "Python", "Rust"]
