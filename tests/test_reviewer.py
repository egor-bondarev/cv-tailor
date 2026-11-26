import subprocess
from pathlib import Path

from cvtailor.config import Config
from cvtailor.reviewer import resolve_reviewer, run_review

REPO = Path(__file__).resolve().parents[1]


def cfg(**kw):
    return Config(output_folder_id="o", **kw)


def test_resolve_auto_without_binary():
    assert resolve_reviewer(cfg(), which=lambda name: None) is None
    assert resolve_reviewer(cfg(), which=lambda name: "/bin/codex") == ["codex", "exec", "-"]


def test_resolve_none():
    assert resolve_reviewer(cfg(second_reviewer="none"), which=lambda n: "/bin/x") is None


class Runner:
    def __init__(self, stdout="", returncode=0, exc=None):
        self.stdout, self.returncode, self.exc, self.calls = stdout, returncode, exc, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.returncode, stdout=self.stdout, stderr="err")


GOOD = 'log {"x": 1}\n{"verdicts": [{"op": 1, "verdict": "supported"}, {"op": 9, "verdict": "partial"}]}'


def test_run_review_uses_temp_cwd():
    r = Runner(GOOD)
    run_review(["codex"], "prompt", "pack", [1], 10, run=r)
    cwd = Path(r.calls[0][1]["cwd"])
    assert REPO not in cwd.parents and cwd != REPO
    assert r.calls[0][1]["input"].startswith("prompt") and "pack" in r.calls[0][1]["input"]


def test_run_review_parses_last_top_level_json_and_drops_unknown_ops():
    review, status = run_review(["codex"], "p", "k", [1], 10, run=Runner(GOOD))
    assert status == "codex" and [v.op for v in review.verdicts] == [1]


def test_run_review_not_configured():
    assert run_review(None, "p", "k", [1], 10) == (None, "none: not configured")


def test_run_review_timeout_status():
    review, status = run_review(["codex"], "p", "k", [1], 10, run=Runner(exc=subprocess.TimeoutExpired("codex", 10)))
    assert review is None and status.startswith("none: timeout")


def test_run_review_nonzero_exit_status():
    review, status = run_review(["codex"], "p", "k", [1], 10, run=Runner(GOOD, returncode=2))
    assert review is None and "exit 2" in status


def test_run_review_garbage_status():
    review, status = run_review(["codex"], "p", "k", [1], 10, run=Runner("no json"))
    assert review is None and status.startswith("none:")


def test_run_review_missing_binary():
    review, status = run_review(["codex"], "p", "k", [1], 10, run=Runner(exc=FileNotFoundError("codex")))
    assert review is None and status.startswith("none:")
