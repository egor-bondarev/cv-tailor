"""cvtailor command line: facts check, init, next, final, login."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cvtailor.config import Config, ConfigError, ResumeConfig, load_config, load_resumes
from cvtailor.facts import FactsError, check_facts, load_facts
from cvtailor.google_api import AuthRequired, GoogleClient, login
from cvtailor.models import ParseError
from cvtailor.parse import parse_resume


def make_client(repo: Path, cfg: Config, resumes: list[ResumeConfig]) -> GoogleClient:
    allowed = {r.doc_id for r in resumes}
    try:
        return GoogleClient.from_token(repo, allowed, cfg.output_folder_id)
    except AuthRequired as exc:
        print(f"{exc}; opening the browser to sign in to Google", file=sys.stderr)
        login(repo)
        return GoogleClient.from_token(repo, allowed, cfg.output_folder_id)


def cmd_facts_check(repo: Path, offline: bool) -> int:
    try:
        cfg = load_config(repo)
        facts = load_facts(repo / cfg.facts_path)
        resume_cfgs = [] if offline else load_resumes(repo)
    except (ConfigError, FactsError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}")
        return 1

    resumes = None
    parse_problems: list[str] = []
    if not offline:
        client = make_client(repo, cfg, resume_cfgs)
        resumes = {}
        for r in resume_cfgs:
            try:
                resumes[r.id] = parse_resume(client.get_doc(r.doc_id), r.editable_companies)
            except ParseError as exc:
                parse_problems.append(f"{r.id}: cannot parse resume: {exc}")

    report = check_facts(facts, resumes)
    problems = parse_problems + report.problems
    s = report.stats
    print(f"{s['facts']} facts, {s['verified']} verified, {s['roles']} roles, {s['skills']} skills"
          + ("" if offline else f"; checked against {len(resumes)} resumes"))
    for w in report.warnings:
        print(f"warning: {w}")
    for p in problems:
        print(f"problem: {p}")
    print("OK" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


def _deps(repo: Path):
    from cvtailor.state import Deps
    cfg = load_config(repo)
    resumes = load_resumes(repo)
    facts = load_facts(repo / cfg.facts_path)
    allowed = {r.doc_id for r in resumes}
    return Deps(repo=repo, cfg=cfg, resumes=resumes, facts=facts,
                client_factory=lambda: GoogleClient.from_token(repo, allowed, cfg.output_folder_id))


def _run_dir(repo: Path, run: str | None) -> Path:
    if run:
        return Path(run)
    current = repo / "runs" / ".current"
    if not current.exists():
        raise ConfigError("no current run: start one with `cvtailor init`")
    return repo / "runs" / current.read_text().strip()


def _print_action(act) -> int:
    print(act.model_dump_json(exclude_none=True))
    return 0


def cmd_init(repo: Path, company: str, resume: str | None) -> int:
    from datetime import date
    from cvtailor.state import init_run
    try:
        state = init_run(repo, company, sys.stdin.read(), resume, load_resumes(repo), date.today())
    except (ConfigError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(state.run_dir)
    return 0


def cmd_next(repo: Path, run: str | None, answer: str | None, from_step: str | None) -> int:
    from cvtailor.state import Action, RunState, next_action
    try:
        deps = _deps(repo)
        state = RunState.load(_run_dir(repo, run))
    except (ConfigError, FactsError, FileNotFoundError) as exc:
        _print_action(Action(action="say", step="config", text=f"ERROR: {exc}"))
        return 1
    return _print_action(next_action(state, deps, answer=answer, from_step=from_step))


def cmd_final(repo: Path, run: str | None) -> int:
    import json
    from cvtailor.models import Op
    from cvtailor.report import acceptance
    from cvtailor.state import Action, RunState
    from cvtailor.verify import final_check
    try:
        deps = _deps(repo)
        state = RunState.load(_run_dir(repo, run))
    except (ConfigError, FactsError, FileNotFoundError) as exc:
        _print_action(Action(action="say", step="final", text=f"ERROR: {exc}"))
        return 1
    if not state.copy_id or not state.applied:
        _print_action(Action(action="say", step="final", text="no copy with applied edits in this run yet"))
        return 1
    rc = next(r for r in deps.resumes if r.id == state.resume_id)
    try:
        final_doc = deps.client_factory().get_doc(state.copy_id)
    except AuthRequired:
        _print_action(Action(action="auth", step="final", text="run `cvtailor login`, then `cvtailor final`"))
        return 1
    run_dir = state.path
    before = json.loads((run_dir / "copy.json").read_text())
    resume = parse_resume(before, rc.editable_companies)
    ops = [Op(**o) for o in json.loads((run_dir / "plan.json").read_text())["ops"]]
    report = final_check(before, final_doc, resume, rc.editable_companies)
    outcomes = []
    try:
        outcomes = acceptance(resume, parse_resume(final_doc, rc.editable_companies), ops)
    except ParseError:
        pass
    counts = {k: sum(o.outcome == k for o in outcomes) for k in ("accepted", "edited", "rejected")}
    (run_dir / "final.json").write_text(json.dumps({"ok": report.ok, "problems": report.problems,
                                                    "outcomes": [o.model_dump() for o in outcomes], "counts": counts}, indent=2))
    text = ("Final check OK." if report.ok else "Final check found problems: " + "; ".join(report.problems[:5]))
    text += f" Edits: {counts['accepted']} accepted, {counts['edited']} edited, {counts['rejected']} rejected."
    _print_action(Action(action="say", step="final", text=text))
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cvtailor")
    sub = parser.add_subparsers(dest="group")
    facts = sub.add_parser("facts", help="fact base commands")
    facts_sub = facts.add_subparsers(dest="command")
    check = facts_sub.add_parser("check", help="validate facts.json and its quotes against the resumes")
    check.add_argument("--offline", action="store_true", help="skip reading resumes from Google")
    check.add_argument("--repo", default=".", help="repository root (default: current directory)")

    init = sub.add_parser("init", help="start a run; vacancy text on stdin")
    init.add_argument("--company", required=True)
    init.add_argument("--resume", help="skip routing and use this resume id")
    init.add_argument("--repo", default=".")
    nxt = sub.add_parser("next", help="advance the current run and print the next action as JSON")
    nxt.add_argument("--run")
    nxt.add_argument("--answer")
    nxt.add_argument("--from", dest="from_step")
    nxt.add_argument("--repo", default=".")
    fin = sub.add_parser("final", help="check the copy after you resolved all suggestions in Google Docs")
    fin.add_argument("--run")
    fin.add_argument("--repo", default=".")
    lgn = sub.add_parser("login", help="sign in to Google (opens a browser)")
    lgn.add_argument("--repo", default=".")

    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.group == "facts" and getattr(args, "command", None) == "check":
        return cmd_facts_check(Path(args.repo), args.offline)
    if args.group == "init":
        return cmd_init(Path(args.repo), args.company, args.resume)
    if args.group == "next":
        return cmd_next(Path(args.repo), args.run, args.answer, args.from_step)
    if args.group == "final":
        return cmd_final(Path(args.repo), args.run)
    if args.group == "login":
        login(Path(args.repo))
        print("signed in")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
