"""`cvtailor run`: drive the state machine to the next stop, calling the model for every AI step (v2 V1)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from cvtailor.ai import CallRecord, call_model
from cvtailor.state import Action, Deps, RunState, next_action

CONTINUE_TEXT = ("Progress saved after {s:.0f}s (time budget per call is {b}s); "
                 "run `cvtailor run` again to continue.")


def _log_call(run_dir: Path, rec: CallRecord) -> None:
    with (run_dir / "ai_calls.jsonl").open("a") as f:
        f.write(rec.model_dump_json() + "\n")


def run_until_stop(
    run_dir: Path, deps: Deps, answer: str | None = None, from_step: str | None = None,
    ask: Callable[[Action], str | None] | None = None, auto_answer: bool = False,
    log: Callable[[str], None] = lambda msg: None,
    call: Callable[..., CallRecord] | None = None, clock: Callable[[], float] = time.monotonic,
) -> Action:
    """Returns the first action that needs a person: a question (unless `ask` or `auto_answer` handles it),
    a message, sign-in, the end of the run, or `continue` when the time budget is spent."""
    settings = deps.cfg.ai
    call = call or call_model
    started = clock()
    first = True
    while True:
        elapsed = clock() - started
        if not first and elapsed > settings.max_run_seconds:
            state = RunState.load(run_dir)
            return Action(action="continue", step=state.step,
                          text=CONTINUE_TEXT.format(s=elapsed, b=settings.max_run_seconds))
        act = next_action(RunState.load(run_dir), deps, answer=answer, from_step=from_step if first else None)
        first, answer = False, None
        if act.action == "ai":
            log(f"{act.step}: calling the model{' (retry)' if act.errors else ''}")
            rec = call(act.step, Path(act.prompt), Path(act.input), Path(act.output), bool(act.errors), settings)
            _log_call(run_dir, rec)
            if not rec.ok:
                return Action(action="say", step=act.step,
                              text=f"{act.step}: AI call failed ({rec.error}). Fix the cause and run `cvtailor run` again.")
            log(f"{act.step}: answer in {rec.seconds}s")
            continue
        if act.action == "ask_user":
            if auto_answer and act.options:
                state = RunState.load(run_dir)
                state.notes.append(f"{act.step}: picked {act.options[0]!r} without asking (--non-interactive)")
                state.save()
                answer = "1"
                continue
            if ask is not None:
                got = ask(act)
                if got:
                    answer = got
                    continue
        return act
