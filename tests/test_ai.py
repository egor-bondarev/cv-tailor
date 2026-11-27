import json
import subprocess
from pathlib import Path

from cvtailor.ai import AiSettings, build_message, call_model, latest_attempt


class Run:
    def __init__(self, stdout="", returncode=0, exc=None, stderr=""):
        self.stdout, self.returncode, self.exc, self.stderr, self.calls = stdout, returncode, exc, stderr, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.returncode, stdout=self.stdout, stderr=self.stderr)


def files(tmp_path):
    (tmp_path / "p.md").write_text("PROMPT")
    (tmp_path / "in.md").write_text("PACK")
    return tmp_path / "p.md", tmp_path / "in.md", tmp_path / "out.json"


def call(tmp_path, run, errors=False, settings=None):
    p, i, o = files(tmp_path)
    return call_model("tailor", p, i, o, errors, settings or AiSettings(), run=run), o


def test_claude_wrapper_is_unwrapped_and_usage_logged(tmp_path):
    out = {"type": "result", "is_error": False, "result": '{"ops": []}', "total_cost_usd": 0.12,
           "usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "cache_creation_input_tokens": 7, "output_tokens": 3}}
    run = Run(json.dumps(out))
    rec, o = call(tmp_path, run)
    assert rec.ok and o.read_text() == '{"ops": []}'
    assert (rec.model, rec.input_tokens, rec.cache_read_tokens, rec.output_tokens, rec.cost_usd) == ("opus", 10, 5, 3, 0.12)
    cmd, kw = run.calls[0]
    assert cmd[:4] == ["claude", "-p", "--model", "opus"] and "" in cmd
    assert "PROMPT" in kw["input"] and "PACK" in kw["input"] and "previous answer" not in kw["input"]
    assert kw["cwd"] != str(tmp_path)


def test_plain_stdout_is_written_as_is(tmp_path):
    rec, o = call(tmp_path, Run('text {"ops": []}'), settings=AiSettings(command=["my-ai", "{model}"]))
    assert rec.ok and o.read_text() == 'text {"ops": []}' and rec.input_tokens is None


def test_model_error_writes_nothing(tmp_path):
    rec, o = call(tmp_path, Run(json.dumps({"type": "result", "is_error": True, "result": "Failed to authenticate"})))
    assert not rec.ok and "authenticate" in rec.error and not o.exists()


def test_exit_code_and_timeout_and_missing_binary(tmp_path):
    rec, o = call(tmp_path, Run("", returncode=2, stderr="boom"))
    assert not rec.ok and "exit 2: boom" in rec.error and not o.exists()
    rec, _ = call(tmp_path, Run(exc=subprocess.TimeoutExpired("claude", 5)))
    assert "timeout" in rec.error
    rec, _ = call(tmp_path, Run(exc=FileNotFoundError("claude")))
    assert "cannot start claude" in rec.error


def test_retry_includes_newest_previous_answer(tmp_path):
    p, i, o = files(tmp_path)
    (tmp_path / "out.json.attempt2").write_text("SECOND")
    (tmp_path / "out.json.attempt10").write_text("TENTH")
    (tmp_path / "out.json.stale1").write_text("STALE")
    assert latest_attempt(o).name == "out.json.attempt10"
    run = Run('{"ops": []}')
    rec = call_model("extract", p, i, o, True, AiSettings(), run=run)
    msg = run.calls[0][1]["input"]
    assert rec.retry and rec.model == "sonnet" and "TENTH" in msg and "SECOND" not in msg and "STALE" not in msg


def test_build_message_order():
    m = build_message("P", "I", "PREV")
    assert m.index("P") < m.index("# Input") < m.index("PREV") < m.index("JSON object only")
