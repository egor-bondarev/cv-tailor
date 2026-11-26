"""Second-model review of planned edits, run as an isolated subprocess (DESIGN.md §8)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from typing import Callable

from cvtailor.checks import parse_json_text
from cvtailor.config import Config
from cvtailor.schemas import Review


def resolve_reviewer(cfg: Config, which: Callable[[str], str | None] = shutil.which) -> list[str] | None:
    if cfg.second_reviewer == "none" or not cfg.reviewer_command:
        return None
    return cfg.reviewer_command if which(cfg.reviewer_command[0]) else None


def run_review(
    command: list[str] | None, prompt: str, pack: str, op_ids: list[int], timeout_s: int,
    run: Callable = subprocess.run,
) -> tuple[Review | None, str]:
    """Never raises. Runs in an empty temp dir so the reviewer cannot read repository files."""
    if not command:
        return None, "none: not configured"
    try:
        with tempfile.TemporaryDirectory(prefix="cvtailor-review-") as cwd:
            proc = run(command, input=prompt + "\n\n" + pack, capture_output=True, text=True,
                       timeout=timeout_s, cwd=cwd)
    except subprocess.TimeoutExpired:
        return None, f"none: timeout after {timeout_s}s"
    except OSError as exc:
        return None, f"none: cannot start {command[0]} ({exc})"
    if proc.returncode != 0:
        return None, f"none: {command[0]} exit {proc.returncode}"
    review, errors = parse_json_text(proc.stdout or "", Review)
    if review is None:
        return None, f"none: unreadable answer ({errors[0].detail})"
    wanted = set(op_ids)
    return review.model_copy(update={"verdicts": [v for v in review.verdicts if v.op in wanted]}), command[0]
