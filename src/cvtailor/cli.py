"""cvtailor command line: facts check, init, next, run, letter, final, login."""

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
    from cvtailor.profile import load_profile
    profile = load_profile(repo / cfg.profile_path)
    allowed = {r.doc_id for r in resumes}
    return Deps(repo=repo, cfg=cfg, resumes=resumes, facts=facts, profile=profile,
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


def _vacancy(company: str | None, url: str | None, paste: bool = False) -> dict:
    """init_run arguments for a new run: the vacancy text from stdin or, with only a link, from the page."""
    from cvtailor.fetch import FetchError, fetch_vacancy
    text = "" if url and sys.stdin.isatty() else sys.stdin.read()  # with a link, a terminal is not waited on
    page_html = None
    if url and not text.strip():
        try:
            page = fetch_vacancy(url)
        except FetchError as exc:
            if not paste:
                raise ConfigError(
                    f"cannot read the vacancy page: {exc}. Read the page another way (a browser or your web tool) "
                    f"and pass its text on stdin with the same --url, or paste the vacancy text") from None
            print(f"Cannot read the vacancy page: {exc}.\nPaste the vacancy text, then press Ctrl-D:",
                  file=sys.stderr)
            text = sys.stdin.read()
        else:
            text, page_html, url = page.text, page.html, page.url
            company = company or page.company
    if not company:
        raise ConfigError("company name not found" + (" on the page" if url else "") + ": pass --company")
    return {"company": company, "vacancy_text": text, "url": url, "page_html": page_html}


def cmd_init(repo: Path, company: str | None, resume: str | None, url: str | None = None) -> int:
    from datetime import date
    from cvtailor.state import init_run
    try:
        state = init_run(repo, forced_resume=resume, resumes=load_resumes(repo), today=date.today(),
                         **_vacancy(company, url))
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
    from cvtailor.state import LOCKED_TEXT, RunLocked, run_lock
    try:
        with run_lock(state.path):
            return _print_action(next_action(state, deps, answer=answer, from_step=from_step))
    except RunLocked:
        return _print_action(Action(action="say", step=state.step, text=LOCKED_TEXT))


def _ask_terminal(act) -> str | None:
    print(act.question, file=sys.stderr)
    for i, opt in enumerate(act.options, 1):
        print(f"  {i}) {opt}", file=sys.stderr)
    try:
        return input("answer> ").strip() or None
    except EOFError:
        return None


def _print_human(act) -> None:
    if act.action == "ask_user":
        print(act.question)
        print(f"Answer with `cvtailor run --answer <number>`: "
              + ", ".join(f"{i}) {o}" for i, o in enumerate(act.options, 1)))
    else:
        print(act.text or act.action)


def cmd_run(repo: Path, company: str | None, resume: str | None, run: str | None, answer: str | None,
            from_step: str | None, non_interactive: bool, as_json: bool, url: str | None = None) -> int:
    from datetime import date
    from cvtailor.autorun import run_until_stop
    from cvtailor.state import Action, init_run
    try:
        deps = _deps(repo)
        if company or url:
            paste = not as_json and not non_interactive and sys.stdin.isatty()
            run_dir = Path(init_run(repo, forced_resume=resume, resumes=deps.resumes, today=date.today(),
                                    **_vacancy(company, url, paste)).run_dir)
        else:
            run_dir = _run_dir(repo, run)
    except (ConfigError, FactsError, FileNotFoundError) as exc:
        act = Action(action="say", step="config", text=f"ERROR: {exc}")
        _print_action(act) if as_json else print(act.text)
        return 1
    interactive = not as_json and not non_interactive and sys.stdin.isatty()
    act = run_until_stop(run_dir, deps, answer=answer, from_step=from_step,
                         ask=_ask_terminal if interactive else None, auto_answer=non_interactive,
                         log=lambda m: print(f"[cvtailor] {m}", file=sys.stderr, flush=True))
    if as_json:
        return _print_action(act)
    _print_human(act)
    return 0


def cmd_letter(repo: Path, run: str | None, feedback: str | None, mode: str | None, max_chars: int | None,
               no_run: bool, as_json: bool) -> int:
    """Write the cover letter again for a run: with the candidate's requests, a shorter mode or a character limit."""
    from cvtailor.autorun import run_until_stop
    from cvtailor.state import LOCKED_TEXT, Action, RunLocked, RunState, run_lock
    try:
        deps = _deps(repo)
        run_dir = _run_dir(repo, run)
        state = RunState.load(run_dir)
    except (ConfigError, FactsError, FileNotFoundError) as exc:
        act = Action(action="say", step="letter", text=f"ERROR: {exc}")
        _print_action(act) if as_json else print(act.text)
        return 1
    if not state.applied and state.step not in ("letter", "report", "done"):
        act = Action(action="say", step=state.step, text="the resume part of this run is not finished yet: "
                     "run `cvtailor run` first; the letter is written right after the resume edits")
        _print_action(act) if as_json else print(act.text)
        return 1
    try:
        with run_lock(run_dir):
            state = RunState.load(run_dir)
            if feedback:
                state.letter_feedback.append(feedback.strip())
            if max_chars:
                state.letter_max_chars = max_chars
            elif mode:
                state.letter_mode, state.letter_max_chars = mode, None
            state.letter_revise = True
            state.save()
    except RunLocked:
        act = Action(action="say", step=state.step, text=LOCKED_TEXT)
        _print_action(act) if as_json else print(act.text)
        return 1
    if no_run:
        print("Saved. Run `cvtailor next --from letter` (manual mode) or `cvtailor run --from letter`.")
        return 0
    act = run_until_stop(run_dir, deps, from_step="letter",
                         log=lambda m: print(f"[cvtailor] {m}", file=sys.stderr, flush=True))
    result = run_dir / "letter_result.json"
    if act.step == "report" and act.action == "say" and result.exists():
        # a rewrite only changes the letter: show its part of the summary, not the resume's again
        import json
        from cvtailor.report import letter_lines
        r = json.loads(result.read_text())
        tail = ['Read the letter; say what to change, or "ok" to run the final check and export both to PDF.']
        act = act.model_copy(update={"text": "\n".join(letter_lines(r) + (tail if r.get("ok") else [])) + "\n"})
    if as_json:
        return _print_action(act)
    _print_human(act)
    return 0


def export_pdfs(client, state, deps) -> str:
    """Export the resume copy and the cover letter to PDF in the company folder; re-export replaces the files."""
    import json
    from cvtailor.letter import pdf_names
    from cvtailor.schemas import Vacancy
    vacancy = Vacancy.model_validate(json.loads((state.path / "vacancy.json").read_text()))
    names = pdf_names(deps.profile, vacancy, state.copy_name or "Resume", state.letter_name if state.letter_id else None)
    sources = {"resume": state.copy_id, "letter": state.letter_id}
    done = []
    for key, name in names.items():
        file_id = client.upload_pdf(name, state.folder_id, client.export_pdf(sources[key]), state.pdf_ids.get(key))
        state.pdf_ids[key] = file_id
        state.save()
        done.append(f"{name} (https://drive.google.com/file/d/{file_id}/view)")
    return "PDF in the company folder: " + "; ".join(done) + "."


def cmd_final(repo: Path, run: str | None, fix_layout: bool = False, export: bool = True,
              keep_layout: bool = False) -> int:
    import json
    from cvtailor.docmodel import has_suggestions
    from cvtailor.layout import check_layout
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
        client = deps.client_factory()
        final_doc = client.get_doc(state.copy_id)
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
    layout, split_left = "", False
    if not has_suggestions(final_doc):
        try:
            res = check_layout(client, state.copy_id, fix_layout)
            layout = res.text(fix_layout)
            split_left = bool(res.split) and not res.problem  # a role longer than a page cannot be fixed
        except AuthRequired:
            _print_action(Action(action="auth", step="final", text="run `cvtailor login`, then `cvtailor final`"))
            return 1
        except Exception as exc:  # the layout check is advisory: never hide the final check behind it
            layout = f"Layout check skipped ({type(exc).__name__}: {str(exc)[:120]})."
    exported = ""
    if export and split_left and not keep_layout:
        exported = ("PDF not exported: a role is split across pages. Run `cvtailor final --fix-layout` to move it "
                    "and export, or `cvtailor final --keep-layout` to export as it is.")
    elif export and deps.cfg.cover_letter.export_pdf and report.ok and not has_suggestions(final_doc) and state.folder_id:
        try:
            exported = export_pdfs(client, state, deps)
        except AuthRequired:
            _print_action(Action(action="auth", step="final", text="run `cvtailor login`, then `cvtailor final`"))
            return 1
        except Exception as exc:
            exported = f"PDF export failed ({type(exc).__name__}: {str(exc)[:120]}); run `cvtailor final` again."
    elif export and has_suggestions(final_doc):
        exported = "PDF not exported yet: resolve every suggestion first."
    (run_dir / "final.json").write_text(json.dumps({"ok": report.ok, "problems": report.problems,
                                                    "outcomes": [o.model_dump() for o in outcomes], "counts": counts,
                                                    "layout": layout, "pdf": exported}, indent=2))
    text = ("Final check OK." if report.ok else "Final check found problems: " + "; ".join(report.problems[:5]))
    text += f" Edits: {counts['accepted']} accepted, {counts['edited']} edited, {counts['rejected']} rejected."
    if layout:
        text += " " + layout
    if exported:
        text += " " + exported
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

    init = sub.add_parser("init", help="start a run; vacancy text on stdin or --url")
    init.add_argument("--company", help="required unless the --url page names the company")
    init.add_argument("--url", help="vacancy link: the page is downloaded unless the text is on stdin")
    init.add_argument("--resume", help="skip routing and use this resume id")
    init.add_argument("--repo", default=".")
    nxt = sub.add_parser("next", help="advance the current run and print the next action as JSON")
    nxt.add_argument("--run")
    nxt.add_argument("--answer")
    nxt.add_argument("--from", dest="from_step")
    nxt.add_argument("--repo", default=".")
    rn = sub.add_parser("run", help="run the pipeline, calling the model for every AI step, until it needs you")
    rn.add_argument("--company", help="start a new run for this company; vacancy text on stdin")
    rn.add_argument("--url", help="start a new run from a vacancy link (company from the page unless --company)")
    rn.add_argument("--resume", help="with --company: skip routing and use this resume id")
    rn.add_argument("--run", help="continue this run folder (default: the current run)")
    rn.add_argument("--answer", help="answer to the pending question")
    rn.add_argument("--from", dest="from_step")
    rn.add_argument("--non-interactive", action="store_true", help="never ask: take the top-ranked option")
    rn.add_argument("--json", dest="as_json", action="store_true", help="print the stopping action as one JSON line")
    rn.add_argument("--repo", default=".")
    fin = sub.add_parser("final", help="check the copy after you resolved all suggestions in Google Docs")
    fin.add_argument("--run")
    fin.add_argument("--fix-layout", action="store_true",
                     help="move a role split across two pages to the next page (edits the copy directly)")
    fin.add_argument("--repo", default=".")
    fin.add_argument("--keep-layout", action="store_true",
                     help="export the PDFs even though a role is split across pages")
    fin.add_argument("--no-export", action="store_true",
                     help="do not export the resume and the cover letter to PDF after a clean check")
    let = sub.add_parser(
        "letter", help="write the cover letter of a run again: with requested changes, shorter, or within a limit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Rewrite the cover letter of a run (default: the current run) and update its Google Doc.\n"
            "The letter is first written by `cvtailor run` right after the resume edits; use this command\n"
            "for changes. Requests accumulate across calls. Calls the model like `cvtailor run`.\n\n"
            "Reads: the run folder, facts.json, profile.yaml (motivation, relocation, contacts for the header).\n"
            "Writes: runs/<run>/letter.json, letter.txt, letter_result.json, summary.txt; the letter Google Doc\n"
            "(a new document if the old one was edited by hand). Network: Google Drive and Docs, the model."),
        epilog=(
            "lengths (characters with spaces, without the contacts header):\n"
            "  full   1300-1800, at most 2000 (default)\n"
            "  short  650-900, at most 1000\n"
            "  --max-chars N   at most N, for a site with a field limit\n\n"
            "examples:\n"
            "  cvtailor letter --feedback \"mention the metrics dashboards, drop the relocation sentence\"\n"
            "  cvtailor letter --short\n"
            "  cvtailor letter --max-chars 900 --json\n\n"
            "output: the run summary as text, or with --json one action line as for `cvtailor run`.\n"
            "exit code: 0 when the command ran (check the action), 1 on a configuration error."))
    let.add_argument("--feedback", help="what to change, in the candidate's words")
    size = let.add_mutually_exclusive_group()
    size.add_argument("--short", dest="mode", action="store_const", const="short", help="short letter (650-900)")
    size.add_argument("--full", dest="mode", action="store_const", const="full", help="full letter (1300-1800)")
    size.add_argument("--max-chars", type=int, metavar="N", help="hard character limit, e.g. a form field")
    let.add_argument("--run", help="run folder (default: the current run)")
    let.add_argument("--no-run", action="store_true",
                     help="only save the request; then `cvtailor next --from letter` for manual mode")
    let.add_argument("--json", dest="as_json", action="store_true", help="print the stopping action as one JSON line")
    let.add_argument("--repo", default=".")
    lgn = sub.add_parser("login", help="sign in to Google (opens a browser)")
    lgn.add_argument("--repo", default=".")

    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.group == "facts" and getattr(args, "command", None) == "check":
        return cmd_facts_check(Path(args.repo), args.offline)
    if args.group == "init":
        if not args.company and not args.url:
            parser.error("init needs --company or --url")
        return cmd_init(Path(args.repo), args.company, args.resume, args.url)
    if args.group == "next":
        return cmd_next(Path(args.repo), args.run, args.answer, args.from_step)
    if args.group == "run":
        return cmd_run(Path(args.repo), args.company, args.resume, args.run, args.answer, args.from_step,
                       args.non_interactive, args.as_json, args.url)
    if args.group == "final":
        return cmd_final(Path(args.repo), args.run, args.fix_layout, not args.no_export, args.keep_layout)
    if args.group == "letter":
        if args.max_chars is not None and args.max_chars < 300:
            parser.error("--max-chars must be at least 300")
        return cmd_letter(Path(args.repo), args.run, args.feedback, args.mode, args.max_chars, args.no_run,
                          args.as_json)
    if args.group == "login":
        login(Path(args.repo))
        print("signed in")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
