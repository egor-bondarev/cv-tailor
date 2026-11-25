"""cvtailor command line. Implemented: `facts check`."""

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cvtailor")
    sub = parser.add_subparsers(dest="group")
    facts = sub.add_parser("facts", help="fact base commands")
    facts_sub = facts.add_subparsers(dest="command")
    check = facts_sub.add_parser("check", help="validate facts.json and its quotes against the resumes")
    check.add_argument("--offline", action="store_true", help="skip reading resumes from Google")
    check.add_argument("--repo", default=".", help="repository root (default: current directory)")

    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.group == "facts" and getattr(args, "command", None) == "check":
        return cmd_facts_check(Path(args.repo), args.offline)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
