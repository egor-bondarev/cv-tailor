"""Scripted AI steps: call a model as an isolated subprocess (v2 V1).

Each call gets only the step prompt and the step input (plus the previous answer on a retry), runs in an
empty temp dir with tools disabled, and writes the model's answer to the step's output file. Python then
validates it exactly as it validates an answer written by a chat agent.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

SYSTEM_PROMPT = ("You are one step of a scripted pipeline. Follow the step instructions in the user message. "
                 "You cannot read or write files: answer with exactly one JSON object and nothing else.")


class AiSettings(BaseModel):
    command: list[str] = ["claude", "-p", "--model", "{model}", "--output-format", "json", "--tools", "",
                          "--no-session-persistence", "--strict-mcp-config", "--system-prompt", SYSTEM_PROMPT]
    models: dict[str, str] = {"extract": "sonnet", "route": "sonnet", "analyze": "sonnet", "tailor": "opus"}
    default_model: str = "sonnet"
    timeout_s: int = 240
    max_run_seconds: int = 240


class CallRecord(BaseModel):
    step: str
    model: str
    ok: bool
    error: str = ""
    seconds: float = 0.0
    retry: bool = False
    input_chars: int = 0
    output_chars: int = 0
    input_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


def latest_attempt(output: Path) -> Path | None:
    found = []
    for p in output.parent.glob(output.name + ".attempt*"):
        m = re.fullmatch(re.escape(output.name) + r"\.attempt(\d+)", p.name)
        if m:
            found.append((int(m.group(1)), p))
    return max(found)[1] if found else None


def build_message(prompt: str, pack: str, previous: str | None) -> str:
    parts = [prompt.strip(), "---\n\n# Input\n\n" + pack.strip()]
    if previous is not None:
        parts.append("---\n\n# Your previous answer (rejected; fix the errors listed at the top of the input)\n\n"
                     + previous.strip())
    parts.append("---\n\nAnswer with the JSON object only.")
    return "\n\n".join(parts) + "\n"


def _unwrap(stdout: str) -> tuple[str, dict, float | None, str]:
    """`claude -p --output-format json` wraps the answer; other commands print it as is."""
    try:
        obj = json.loads(stdout)
    except ValueError:
        return stdout, {}, None, ""
    if isinstance(obj, dict) and obj.get("type") == "result":
        if obj.get("is_error"):
            return "", {}, None, str(obj.get("result") or obj.get("subtype") or "error")
        return str(obj.get("result") or ""), obj.get("usage") or {}, obj.get("total_cost_usd"), ""
    return stdout, {}, None, ""


def call_model(step: str, prompt_path: Path, input_path: Path, output_path: Path, errors: bool,
               settings: AiSettings, run: Callable = subprocess.run,
               clock: Callable[[], float] = time.monotonic) -> CallRecord:
    """Never raises. Writes the answer to `output_path` only when the model returned one."""
    model = settings.models.get(step, settings.default_model)
    previous = None
    if errors:
        prev = latest_attempt(output_path)
        previous = prev.read_text() if prev else None
    message = build_message(prompt_path.read_text(), input_path.read_text(), previous)
    command = [part.replace("{model}", model) for part in settings.command]
    rec = CallRecord(step=step, model=model, ok=False, retry=errors, input_chars=len(message))
    started = clock()
    try:
        with tempfile.TemporaryDirectory(prefix="cvtailor-ai-") as cwd:
            proc = run(command, input=message, capture_output=True, text=True, timeout=settings.timeout_s, cwd=cwd)
    except subprocess.TimeoutExpired:
        rec.error = f"timeout after {settings.timeout_s}s"
        return rec
    except OSError as exc:
        rec.error = f"cannot start {command[0]} ({exc})"
        return rec
    finally:
        rec.seconds = round(clock() - started, 1)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
        rec.error = f"{command[0]} exit {proc.returncode}: {tail[0][:200]}"
        return rec
    text, usage, cost, error = _unwrap(proc.stdout or "")
    if error:
        rec.error = f"{command[0]}: {error[:200]}"
        return rec
    output_path.write_text(text)
    rec.ok = True
    rec.output_chars = len(text)
    rec.cost_usd = cost
    if usage:
        rec.input_tokens = usage.get("input_tokens")
        rec.cache_read_tokens = usage.get("cache_read_input_tokens")
        rec.cache_creation_tokens = usage.get("cache_creation_input_tokens")
        rec.output_tokens = usage.get("output_tokens")
    return rec
