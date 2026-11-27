import json
from pathlib import Path

from cvtailor.ai import CallRecord
from cvtailor.autorun import run_until_stop
from cvtailor.config import Config, ResumeConfig
from test_checks import VAC
from test_state import GOOD_OPS, LOOSE, analysis, env, start  # noqa: F401

ROUTE = {"choice": "cv", "confidence": "low", "ranking": ["cv", "cv2"], "reason": "close call"}


class FakeModel:
    """Answers each AI step from `answers[step]` (a list: one answer per call, the last repeats)."""

    def __init__(self, answers, fail=None):
        self.answers, self.fail, self.calls = answers, fail, []

    def __call__(self, step, prompt, inp, out, errors, settings):
        self.calls.append((step, errors))
        if self.fail == step:
            return CallRecord(step=step, model="m", ok=False, error="exit 1")
        seq = self.answers[step]
        out.write_text(json.dumps(seq[min(len([c for c in self.calls if c[0] == step]), len(seq)) - 1]))
        return CallRecord(step=step, model="m", ok=True, seconds=1.0)


ANSWERS = {"extract": [VAC], "route": [ROUTE], "analyze": [analysis()], "tailor": [GOOD_OPS]}


def test_full_run_without_questions(env):
    deps = env.make()
    state = start(env, deps)
    model = FakeModel(ANSWERS)
    act = run_until_stop(Path(state.run_dir), deps, call=model)
    assert act.action == "say" and "2 edits applied" in act.text
    assert [c[0] for c in model.calls] == ["extract", "analyze", "tailor"]
    log = [json.loads(line) for line in Path(state.run_dir, "ai_calls.jsonl").read_text().splitlines()]
    assert [r["step"] for r in log] == ["extract", "analyze", "tailor"]


def two_resumes(env):
    return env.make(resume_list=[ResumeConfig(id="cv", label="Senior SDET", doc_id="doc-1", editable_companies=["acme"]),
                                 ResumeConfig(id="cv2", label="QA", doc_id="doc-2", editable_companies=["acme"])])


def test_question_stops_then_answer_continues(env):
    deps = two_resumes(env)
    state = start(env, deps)
    model = FakeModel(ANSWERS)
    act = run_until_stop(Path(state.run_dir), deps, call=model)
    assert act.action == "ask_user" and act.options == ["cv", "cv2"]
    act = run_until_stop(Path(state.run_dir), deps, answer="1", call=model)
    assert act.action == "say" and "2 edits applied" in act.text


def test_terminal_ask_and_non_interactive(env):
    deps = two_resumes(env)
    state = start(env, deps)
    asked = []
    act = run_until_stop(Path(state.run_dir), deps, ask=lambda a: asked.append(a) or "2", call=FakeModel(ANSWERS))
    assert asked and act.action == "say"
    state2 = start(env, deps)
    act = run_until_stop(Path(state2.run_dir), deps, auto_answer=True, call=FakeModel(ANSWERS))
    assert act.action == "say" and "without asking" in act.text


def test_retry_passes_errors_flag(env):
    deps = env.make()
    state = start(env, deps)
    bad = {"ops": [{"id": 1, "op": "replace", "block": "nope", "new_text": "x", "evidence": ["f-001"]}]}
    model = FakeModel({**ANSWERS, "tailor": [bad, GOOD_OPS]})
    act = run_until_stop(Path(state.run_dir), deps, call=model)
    assert act.action == "say" and ("tailor", True) in model.calls


def test_failed_call_stops_with_message(env):
    deps = env.make()
    state = start(env, deps)
    act = run_until_stop(Path(state.run_dir), deps, call=FakeModel(ANSWERS, fail="analyze"))
    assert act.action == "say" and "analyze: AI call failed (exit 1)" in act.text
    act = run_until_stop(Path(state.run_dir), deps, call=FakeModel(ANSWERS))
    assert act.action == "say" and "2 edits applied" in act.text


def test_time_budget_returns_continue(env):
    deps = env.make(cfg=Config(output_folder_id="out", limits=LOOSE, ai={"max_run_seconds": 10}))
    state = start(env, deps)
    ticks = iter(range(0, 1000, 6))
    act = run_until_stop(Path(state.run_dir), deps, call=FakeModel(ANSWERS), clock=lambda: next(ticks))
    assert act.action == "continue" and "run `cvtailor run` again" in act.text
    act = run_until_stop(Path(state.run_dir), deps, call=FakeModel(ANSWERS))
    assert act.action == "say" and "2 edits applied" in act.text
