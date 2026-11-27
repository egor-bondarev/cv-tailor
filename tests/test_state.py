import copy
import json
from datetime import date
from pathlib import Path

import pytest

from conftest import resume_elements
from cvtailor.config import Config, Limits, ResumeConfig
from cvtailor.facts import load_facts
from cvtailor.google_api import AuthRequired
from cvtailor.models import Op
from cvtailor.parse import parse_resume
from cvtailor.state import Deps, RunState, init_run, next_action
from docbuilder import doc
from docsim import preview_doc
from test_checks import VAC
from test_facts_index import data_with_roles

REPO = Path(__file__).resolve().parents[1]
B1, B2, B3 = "exp.acme.senior-sdet.b01", "exp.acme.senior-sdet.b02", "exp.acme.senior-sdet.b03"
LOOSE = Limits(bullet_replace_max_ratio=10, intro_max_ratio=10, skills_line_max_ratio=10, total_editable_max_ratio=10)
GOOD_OPS = {"ops": [
    {"id": 1, "op": "replace", "block": B1, "new_text": "Built plugin one, now shared.", "evidence": ["f-001"], "reason": "r"},
    {"id": 2, "op": "delete", "block": B3, "reason": "low"},
]}
BAD_OP = {"id": 3, "op": "replace", "block": B2, "new_text": "Built plugin two for 40% more teams.", "evidence": ["f-002"]}


class FakeClient:
    def __init__(self, run_dir_ref):
        self.docs = {"doc-1": doc(*resume_elements(), doc_id="doc-1"), "doc-2": doc(*resume_elements(), doc_id="doc-2")}
        self.folders, self.calls, self.previews, self.fail, self.comments = {}, [], {}, {}, []
        self.run_dir_ref = run_dir_ref
        self.n = 0

    def _maybe_fail(self, name):
        self.calls.append(name)
        exc = self.fail.pop(name, None)
        if exc:
            raise exc

    def list_folders(self, parent):
        self._maybe_fail("list_folders")
        return [(fid, name) for fid, name in self.folders.items()]

    def create_folder(self, name, parent):
        self._maybe_fail("create_folder")
        self.folders["folder-1"] = name
        return "folder-1"

    def list_doc_names(self, folder):
        return set()

    def copy_doc(self, src, name, parent):
        self._maybe_fail("copy_doc")
        self.n += 1
        new = f"copy-{self.n}"
        d = copy.deepcopy(self.docs[src])
        d["documentId"] = new
        self.docs[new] = d
        return new

    def get_doc(self, doc_id, preview_accepted=False):
        self._maybe_fail("get_doc")
        if preview_accepted:
            return self.previews[doc_id]
        return self.docs[doc_id]

    def batch_update(self, doc_id, body):
        self._maybe_fail("batch_update")
        run = Path(self.run_dir_ref[0])
        ops = [Op(**o) for o in json.loads((run / "plan.json").read_text())["ops"]]
        before = self.docs[doc_id]
        resume = parse_resume(before, ["acme"])
        self.previews[doc_id] = preview_doc(before, resume, ops)
        inline = copy.deepcopy(before)
        inline["revisionId"] = "rev-applied"
        inline["body"]["content"][1]["paragraph"]["elements"][0]["textRun"]["suggestedInsertionIds"] = ["s1"]
        self.docs[doc_id] = inline
        self.after_preview_fail = None

    def rename(self, file_id, name):
        self.calls.append(("rename", name))

    def add_comment(self, file_id, text, quote=None):
        self._maybe_fail("add_comment")
        self.comments.append((file_id, text, quote))
        return f"c{len(self.comments)}"


def facts_obj():
    d = data_with_roles()
    for s in d["skills"]:
        if s["name"] == "Kubernetes":
            s["basic"] = True
    return load_facts(d)


@pytest.fixture
def env(tmp_path):
    ref = [None]
    client = FakeClient(ref)
    resumes = [ResumeConfig(id="cv", label="Senior SDET", doc_id="doc-1", editable_companies=["acme"])]
    reviews = []

    def reviewer_run(cmd, **kw):
        import subprocess
        reviews.append(kw)
        return subprocess.CompletedProcess(cmd, 0, stdout='{"verdicts": [{"op": 1, "verdict": "supported"}]}', stderr="")

    def make(resume_list=None, factory=None, cfg=None):
        deps = Deps(repo=REPO, cfg=cfg or Config(output_folder_id="out", limits=LOOSE), resumes=resume_list or resumes,
                    facts=facts_obj(), client_factory=factory or (lambda: client), reviewer_run=reviewer_run,
                    which=lambda n: "/bin/codex", today=date(2026, 11, 25))
        return deps

    class Env:
        pass

    e = Env()
    e.client, e.make, e.reviews, e.ref, e.tmp = client, make, reviews, ref, tmp_path
    return e


def start(env, deps, forced=None):
    state = init_run(env.tmp, "Acme", "We need a Senior SDET", forced, deps.resumes, date(2026, 11, 25))
    env.ref[0] = state.run_dir
    return state


def step(state, deps, **kw):
    act = next_action(RunState.load(Path(state.run_dir)), deps, **kw)
    return act


def write(act, obj):
    Path(act.output).write_text(json.dumps(obj) if not isinstance(obj, str) else obj)


def analysis():
    return {"requirements": [{"text": "Python", "kind": "must", "status": "covered", "fact_ids": ["f-001"]}],
            "relevance": [{"block_id": b, "score": 2, "reason": ""} for b in
                          ["exp.acme.senior-sdet.intro", B1, B2, B3, "exp.acme.qa-engineer.b01", "exp.acme.qa-engineer.b02"]],
            "candidate_facts": ["f-001"]}


def run_to_tailor(env, deps, state):
    a = step(state, deps)
    assert a.action == "ai" and a.step == "extract"
    write(a, VAC)
    a = step(state, deps)
    assert a.action == "ai" and a.step == "analyze", a
    write(a, analysis())
    a = step(state, deps)
    assert a.action == "ai" and a.step == "tailor", a
    return a


def test_happy_path_single_resume(env):
    deps = env.make()
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    a = step(state, deps)
    assert a.action == "say" and "2 edits applied" in a.text
    run = Path(state.run_dir)
    assert (run / "review.md").exists() and (run / "summary.txt").exists()
    assert env.client.calls.count("copy_doc") == 1 and env.client.calls.count("batch_update") == 1
    assert not any(isinstance(c, tuple) and c[0] == "rename" for c in env.client.calls)
    assert json.loads((run / "verify.json").read_text())["ok"]
    assert step(state, deps).action == "done"
    assert env.reviews and Path(env.reviews[0]["cwd"]) != REPO


def two_resumes():
    return [ResumeConfig(id="cv", label="SDET", doc_id="doc-1", editable_companies=["acme"]),
            ResumeConfig(id="cv2", label="QA", doc_id="doc-2", editable_companies=["acme"])]


def test_route_ask_user_and_answer_by_number(env):
    deps = env.make(two_resumes())
    state = start(env, deps)
    a = step(state, deps)
    write(a, VAC)
    a = step(state, deps)
    assert a.step == "route" and a.action == "ai"
    write(a, {"choice": "cv2", "confidence": "medium", "ranking": ["cv2", "cv"], "reason": "close"})
    a = step(state, deps)
    assert a.action == "ask_user" and a.options == ["cv2", "cv"]
    a = step(state, deps, answer="maybe")
    assert a.action == "ask_user" and "not one of" in a.question
    a = step(state, deps, answer="2")
    assert a.action == "ai" and a.step == "analyze"
    assert RunState.load(Path(state.run_dir)).resume_id == "cv"


def test_forced_resume_skips_route(env):
    deps = env.make(two_resumes())
    state = start(env, deps, forced="cv2")
    a = step(state, deps)
    write(a, VAC)
    a = step(state, deps)
    assert a.step == "analyze"


def test_reissue_without_output_does_not_burn_attempt(env):
    deps = env.make()
    state = start(env, deps)
    for _ in range(3):
        a = step(state, deps)
        assert a.action == "ai" and a.step == "extract" and a.errors == []
    st = RunState.load(Path(state.run_dir))
    assert st.attempts.get("extract", 0) == 0 and st.reissues == 2
    step(state, deps)
    a = step(state, deps)
    assert a.action == "say" and "did not write" in a.text


def test_stale_output_is_moved_aside(env):
    deps = env.make()
    state = start(env, deps)
    Path(state.run_dir, "vacancy.json").write_text(json.dumps(VAC))
    a = step(state, deps)
    assert a.action == "ai" and a.step == "extract"
    assert not Path(a.output).exists() and Path(a.output + ".stale1").exists()


def test_invalid_ai_output_is_retried_then_blocks_and_from_unblocks(env):
    deps = env.make()
    state = start(env, deps)
    a = step(state, deps)
    for i in range(2):
        write(a, "not json")
        a = step(state, deps)
        assert a.action == "ai" and a.errors and a.errors[0].rule == "schema"
    write(a, "not json")
    a = step(state, deps)
    assert a.action == "say" and "--from extract" in a.text
    assert step(state, deps).action == "say"
    a = step(state, deps, from_step="extract")
    assert a.action == "ai" and a.step == "extract"


def test_tailor_partial_after_retries(env):
    deps = env.make()
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    plan = {"ops": GOOD_OPS["ops"] + [BAD_OP]}
    for _ in range(2):
        write(a, plan)
        a = step(state, deps)
        assert a.action == "ai" and any(e.rule == "numbers" for e in a.errors)
        assert "40%" in Path(a.input).read_text()
    write(a, plan)
    a = step(state, deps)
    assert a.action == "say" and "2 edits applied, 1 dropped" in a.text
    assert "numbers" in Path(state.run_dir, "review.md").read_text()


def test_next_is_idempotent_after_copy(env):
    deps = env.make()
    state = start(env, deps)
    a = step(state, deps)
    write(a, VAC)
    env.client.fail["get_doc"] = ConnectionError("network")
    assert step(state, deps).action == "say"
    a = step(state, deps)
    assert a.step == "analyze" and env.client.calls.count("copy_doc") == 1


def test_crash_after_apply_resumes_with_verify(env):
    deps = env.make()
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    real_get = env.client.get_doc
    calls = {"n": 0}

    def flaky(doc_id, preview_accepted=False):
        if preview_accepted and calls["n"] == 0:
            calls["n"] += 1
            raise ConnectionError("lost")
        return real_get(doc_id, preview_accepted)

    env.client.get_doc = flaky
    assert step(state, deps).action == "say"
    st = RunState.load(Path(state.run_dir))
    st.applied = False
    st.save()
    a = step(state, deps)
    assert a.action == "say" and "2 edits applied" in a.text
    assert env.client.calls.count("batch_update") == 1


def test_revision_changed_but_text_same_reapplies(env):
    deps = env.make()
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    copy_id = RunState.load(Path(state.run_dir)).copy_id
    env.client.docs[copy_id]["revisionId"] = "rev-new"
    a = step(state, deps)
    assert a.action == "say" and "2 edits applied" in a.text


def test_copy_edited_by_hand_blocks_with_hint(env):
    deps = env.make()
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    copy_id = RunState.load(Path(state.run_dir)).copy_id
    d = env.client.docs[copy_id]
    d["revisionId"] = "rev-new"
    d["body"]["content"][-1]["paragraph"]["elements"][0]["textRun"]["content"] = "Changed by hand\n"
    a = step(state, deps)
    assert a.action == "say" and "--from analyze" in a.text


def test_auth_required_mid_step_returns_auth(env):
    deps = env.make()
    state = start(env, deps)
    a = step(state, deps)
    write(a, VAC)
    env.client.fail["copy_doc"] = AuthRequired("expired")
    a = step(state, deps)
    assert a.action == "auth" and "cvtailor login" in a.text
    a = step(state, deps)
    assert a.step == "analyze"


def test_role_map_error_blocks_before_analyze(env):
    d = data_with_roles()
    d["roles"] = [r for r in d["roles"] if r["id"] != "acme-qa"]
    d["facts"] = [f for f in d["facts"] if f["role_id"] != "acme-qa"]
    for s in d["skills"]:
        s["basic"] = s.get("basic") or not s["evidence"]
    deps = env.make()
    deps.facts = load_facts(d)
    state = start(env, deps)
    a = step(state, deps)
    write(a, VAC)
    a = step(state, deps)
    assert a.action == "say" and "role_map" in a.text


def test_verify_failure_renames_copy(env):
    deps = env.make()
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    real_batch = env.client.batch_update

    def bad_batch(doc_id, body):
        real_batch(doc_id, body)
        env.client.previews[doc_id] = doc(*resume_elements(), doc_id=doc_id)

    env.client.batch_update = bad_batch
    a = step(state, deps)
    assert a.action == "say" and "FAILED" in a.text
    assert any(isinstance(c, tuple) and c[1].startswith("[FAILED]") for c in env.client.calls)


def test_from_copy_after_apply_is_refused(env):
    deps = env.make()
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    step(state, deps)
    a = step(state, deps, from_step="analyze")
    assert a.action == "say" and "new run" in a.text


def test_from_route_after_copy_discards_old_copy(env):
    deps = env.make(two_resumes())
    state = start(env, deps)
    a = step(state, deps)
    write(a, VAC)
    a = step(state, deps)
    write(a, {"choice": "cv", "confidence": "high", "ranking": ["cv", "cv2"], "reason": "r"})
    assert step(state, deps).step == "analyze"
    a = step(state, deps, from_step="route")
    write(a, {"choice": "cv2", "confidence": "high", "ranking": ["cv2", "cv"], "reason": "r"})
    assert step(state, deps).step == "analyze"
    st = RunState.load(Path(state.run_dir))
    assert st.resume_id == "cv2" and st.copy_id == "copy-2" and env.client.calls.count("copy_doc") == 2


def test_unexpected_error_is_single_say_action(env):
    deps = env.make()
    state = start(env, deps)
    a = step(state, deps)
    write(a, VAC)
    env.client.fail["get_doc"] = ConnectionError("network down")
    a = step(state, deps)
    assert a.action == "say" and "network down" in a.text
    assert step(state, deps).step == "analyze"


def test_from_step_ahead_of_current_is_refused(env):
    deps = env.make()
    state = start(env, deps)
    a = step(state, deps, from_step="apply")
    assert a.action == "say" and "ahead" in a.text


def test_auth_error_on_rename_keeps_failed_retry(env):
    deps = env.make()
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    real_batch = env.client.batch_update

    def bad_batch(doc_id, body):
        real_batch(doc_id, body)
        env.client.previews[doc_id] = doc(*resume_elements(), doc_id=doc_id)

    env.client.batch_update = bad_batch
    real_rename = env.client.rename
    fails = {"n": 1}

    def rename(fid, name):
        if fails["n"]:
            fails["n"] -= 1
            raise AuthRequired("expired")
        real_rename(fid, name)

    env.client.rename = rename
    assert step(state, deps).action == "auth"
    step(state, deps)
    assert any(isinstance(c, tuple) and c[1].startswith("[FAILED]") for c in env.client.calls)


def test_auth_during_route_pack_does_not_burn_reissues(env):
    deps = env.make(two_resumes())
    state = start(env, deps)
    a = step(state, deps)
    write(a, VAC)
    for _ in range(5):
        env.client.fail["get_doc"] = AuthRequired("expired")
        assert step(state, deps).action == "auth"
    a = step(state, deps)
    assert a.action == "ai" and a.step == "route"


def test_empty_plan_skips_apply(env):
    deps = env.make()
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, {"ops": []})
    a = step(state, deps)
    assert a.action == "say" and "0 edits applied" in a.text
    assert env.client.calls.count("batch_update") == 0


def flagging_reviewer(env, deps, answers):
    """Reviewer that answers from `answers` in order (the last one repeats)."""
    import subprocess

    def run(cmd, **kw):
        env.reviews.append(kw)
        out = answers[min(len(env.reviews), len(answers)) - 1]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(out), stderr="")

    deps.reviewer_run = run
    return deps


PARTIAL = {"verdicts": [{"op": 1, "verdict": "partial", "quote": "now shared", "comment": "facts do not say shared"}]}
SUPPORTED = {"verdicts": [{"op": 1, "verdict": "supported"}]}
FIXED_OPS = {"ops": [{**GOOD_OPS["ops"][0], "new_text": "Built plugin one."}, GOOD_OPS["ops"][1]]}


def test_reviewer_findings_go_back_to_tailor_once(env):
    deps = flagging_reviewer(env, env.make(), [PARTIAL, SUPPORTED])
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    a = step(state, deps)
    assert a.action == "ai" and a.step == "tailor"
    assert [(e.rule, e.op) for e in a.errors] == [("review", 1)] and "now shared" in a.errors[0].detail
    assert "Errors from previous attempt" in Path(a.input).read_text()
    assert Path(a.output + ".attempt1").exists() and not Path(a.output).exists()
    write(a, FIXED_OPS)
    a = step(state, deps)
    assert a.action == "say" and "2 edits applied" in a.text and "after 1 fix round" in a.text
    assert len(env.reviews) == 2
    assert json.loads(Path(state.run_dir, "plan.json").read_text())["ops"][0]["new_text"] == "Built plugin one."


def test_reviewer_fix_round_is_limited(env):
    deps = flagging_reviewer(env, env.make(), [PARTIAL])
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    a = step(state, deps)
    write(a, GOOD_OPS)  # the model keeps the flagged wording
    a = step(state, deps)
    assert a.action == "say" and "op 1 partial" in a.text and len(env.reviews) == 2


def test_invalid_fix_round_keeps_reviewed_plan(env):
    deps = flagging_reviewer(env, env.make(), [PARTIAL])
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    a = step(state, deps)
    for _ in range(3):
        assert a.action == "ai" and a.step == "tailor"
        write(a, {"ops": [BAD_OP]})
        a = step(state, deps)
    assert a.action == "say" and "2 edits applied" in a.text and "reviewed plan kept" in a.text
    assert len(env.reviews) == 1


def test_no_fix_round_when_disabled(env):
    deps = flagging_reviewer(env, env.make(cfg=Config(output_folder_id="out", limits=LOOSE, review_fix_rounds=0)), [PARTIAL])
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    a = step(state, deps)
    assert a.action == "say" and "op 1 partial" in a.text and len(env.reviews) == 1



def test_each_applied_edit_gets_a_comment(env):
    deps = env.make()
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    a = step(state, deps)
    assert a.action == "say" and "comment in the document" in a.text
    texts = [c[1] for c in env.client.comments]
    assert len(texts) == 2 and "edit 1 of 2 · replace" in texts[0] and "Fact f-001" in texts[0]
    assert "Reviewer (codex): supported" in texts[0] and "Removed bullet." in texts[1]
    assert env.client.comments[0][2] == "Built plugin one, now shared."


def test_auth_during_comments_resumes_without_duplicates(env):
    deps = env.make()
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    real = env.client.add_comment

    def second_fails(file_id, text, quote=None):
        if len(env.client.comments) == 1:
            env.client.add_comment = real
            raise AuthRequired("expired")
        return real(file_id, text, quote)

    env.client.add_comment = second_fails
    a = step(state, deps)
    assert a.action == "auth" and len(env.client.comments) == 1
    a = step(state, deps)
    assert a.action == "say" and len(env.client.comments) == 2
    assert "edit 2 of 2" in env.client.comments[1][1]


def test_comment_error_is_a_note(env):
    deps = env.make()
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    env.client.fail["add_comment"] = RuntimeError("quota")
    a = step(state, deps)
    assert a.action == "say" and "comments: 0 of 2 posted (RuntimeError: quota)" in a.text


def test_comments_can_be_disabled(env):
    deps = env.make(cfg=Config(output_folder_id="out", limits=LOOSE, doc_comments=False))
    state = start(env, deps)
    a = run_to_tailor(env, deps, state)
    write(a, GOOD_OPS)
    a = step(state, deps)
    assert a.action == "say" and env.client.comments == [] and "comment" not in a.text
