from pathlib import Path

from cvtailor.checks import CheckError
from cvtailor.config import ResumeConfig
from cvtailor.models import Op
from cvtailor.packs import analyze_pack, extract_pack, review_pack, route_pack, tailor_pack
from cvtailor.schemas import AiOp, Analysis, Review, Route, Vacancy
from test_checks import VAC
from test_validate import B1, ctx_for

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def vac():
    return Vacancy(**VAC)


def test_extract_pack_contains_vacancy():
    assert "Senior QA wanted" in extract_pack("Senior QA wanted")


def test_route_pack_lists_resumes():
    pack = route_pack(vac(), [(ResumeConfig(id="a", label="A", doc_id="d", target_role="SDET role"), "Summary A")])
    assert "SDET role" in pack and "Summary A" in pack and '"a"' in pack


def test_analyze_pack_excludes_unverified_everywhere():
    ctx = ctx_for()
    pack = analyze_pack(vac(), ctx)
    assert "f-006" not in pack and "Draft fact" not in pack
    assert "f-001" in pack and B1 in pack and "covered_by" in pack and "groups" in pack


def test_tailor_pack_has_limits_errors_no_revision():
    ctx = ctx_for()
    analysis = Analysis(requirements=[], relevance=[], candidate_facts=["f-001", "f-006"])
    pack = tailor_pack(vac(), analysis, ctx, [CheckError(rule="numbers", detail="40% not backed", op=3)])
    assert "bullet_max_chars" in pack and "40% not backed" in pack
    assert "rev-1" not in pack and "base_revision" not in pack
    assert "f-006" not in pack
    assert "Python" in pack


def test_tailor_pack_without_errors_has_no_error_section():
    pack = tailor_pack(vac(), Analysis(requirements=[], relevance=[], candidate_facts=[]), ctx_for(), [])
    assert "Errors from previous attempt" not in pack


def test_review_pack_shows_before_after_and_evidence():
    ctx = ctx_for()
    pack = review_pack([Op(id=1, op="replace", block=B1, new_text="Shiny new text.", evidence=["f-001"])], ctx)
    assert "Built plugin one." in pack and "Shiny new text." in pack and "f-001" in pack


def test_prompts_reference_schema_fields():
    expect = {
        "extract.md": Vacancy, "route.md": Route, "analyze.md": Analysis, "review.md": Review,
    }
    for name, model in expect.items():
        text = (PROMPTS / name).read_text()
        for field in model.model_fields:
            assert field in text, (name, field)
    tailor = (PROMPTS / "tailor.md").read_text()
    for field in AiOp.model_fields:
        assert field in tailor, field
    for op in ("replace", "replace_skills", "insert_after", "delete"):
        assert op in tailor
