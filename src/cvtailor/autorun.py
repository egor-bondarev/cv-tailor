"""`cvtailor run`: drive the state machine to the next stop, calling the model for every AI step (v2 V1)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

from cvtailor.ai import CallRecord, call_model
from cvtailor.checks import load_ai_json
from cvtailor.letter import check_letter, clean_letter, digest, letter_pack
from cvtailor.schemas import LetterAi
from cvtailor.state import (
    LOCKED_TEXT, PREFETCH_ANSWER, PREFETCH_META, Action, Deps, RunLocked, RunState, Runner, next_action, run_letter_review,
    run_lock,
)

CONTINUE_TEXT = ("Progress saved after {s:.0f}s (time budget per call is {b}s); "
                 "run `cvtailor run` again to continue.")


_LOG_LOCK = threading.Lock()


def _log_call(run_dir: Path, rec: CallRecord) -> None:
    with _LOG_LOCK, (run_dir / "ai_calls.jsonl").open("a") as f:
        f.write(rec.model_dump_json() + "\n")


def draft_letter(run_dir: Path, deps: Deps, call: Callable[..., CallRecord], log: Callable[[str], None]) -> None:
    """Write and review the cover letter while the resume edits are planned (v2 V6).

    Touches only its own files: the letter step later adopts the draft if it was made from the same input,
    otherwise it writes the letter as usual. Any failure here only costs the time saved.
    """
    try:
        state = RunState.load(run_dir)
        lctx, analysis, fact_ids = Runner(state, deps).letter_inputs()
        pack = letter_pack(lctx, analysis, fact_ids, [], None, state.letter_feedback)
        inp, raw = run_dir / "letter.prefetch.pack.md", run_dir / PREFETCH_ANSWER
        inp.write_text(pack)
        rec = call("letter", deps.repo / "prompts" / "cover_letter.md", inp, raw, False, deps.cfg.ai)
        rec.parallel = True
        _log_call(run_dir, rec)
        if not rec.ok:
            log(f"letter: draft in parallel failed ({rec.error}); it will be written after the resume")
            return
        meta = {"pack_sha": digest(pack)}
        obj, errors = load_ai_json(raw, LetterAi)
        if obj is not None:
            letter = clean_letter(obj)
            errors, _ = check_letter(letter, lctx)
            if not errors:
                review, status = run_letter_review(letter, lctx, deps)
                meta.update(letter_sha=digest(letter.model_dump()), review_status=status,
                            review=review.model_dump() if review else None)
        tmp = run_dir / (PREFETCH_META + ".tmp")
        tmp.write_text(json.dumps(meta))
        tmp.rename(run_dir / PREFETCH_META)
        log("letter: draft ready" + ("" if meta.get("review_status") else " (to be fixed after the resume)"))
    except Exception as exc:  # never let the parallel draft break the run
        log(f"letter: draft in parallel failed ({type(exc).__name__}: {exc}); it will be written after the resume")


def _wants_draft(run_dir: Path, deps: Deps, act: Action) -> bool:
    if act.step != "tailor" or act.errors or not deps.cfg.cover_letter.enabled:
        return False
    state = RunState.load(run_dir)
    return (state.letter_stage == "write" and not state.letter_round and not state.letter_revise
            and not (run_dir / "letter.json").exists() and not (run_dir / PREFETCH_META).exists())


def run_until_stop(
    run_dir: Path, deps: Deps, answer: str | None = None, from_step: str | None = None,
    ask: Callable[[Action], str | None] | None = None, auto_answer: bool = False,
    log: Callable[[str], None] = lambda msg: None,
    call: Callable[..., CallRecord] | None = None, clock: Callable[[], float] = time.monotonic,
) -> Action:
    """Returns the first action that needs a person: a question (unless `ask` or `auto_answer` handles it),
    a message, sign-in, the end of the run, or `continue` when the time budget is spent."""
    drafts: list[threading.Thread] = []
    try:
        with run_lock(run_dir):
            try:
                return _loop(run_dir, deps, answer, from_step, ask, auto_answer, log, call, clock, drafts)
            finally:
                for t in drafts:
                    t.join()  # inside the lock: a second `run` must not start another draft
    except RunLocked:
        return Action(action="say", step=RunState.load(run_dir).step, text=LOCKED_TEXT)


def _loop(run_dir, deps, answer, from_step, ask, auto_answer, log, call, clock, drafts) -> Action:
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
        state = RunState.load(run_dir)
        if state.step == "letter" and any(t.is_alive() for t in drafts):
            log("letter: waiting for the draft written in parallel")
            for t in drafts:
                t.join()
        act = next_action(state, deps, answer=answer, from_step=from_step if first else None)
        first, answer = False, None
        if act.action == "ai":
            if not drafts and _wants_draft(run_dir, deps, act):
                log("letter: writing in parallel with the resume edits")
                t = threading.Thread(target=draft_letter, args=(run_dir, deps, call, log), daemon=True)
                t.start()
                drafts.append(t)
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
