"""Run state machine behind `cvtailor next` (DESIGN.md §5)."""

from __future__ import annotations

import fcntl
import json
import shutil
from contextlib import contextmanager
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel

from cvtailor.checks import (
    CheckError, check_analysis, check_route, check_vacancy, load_ai_json, parse_plan_ops,
)
from cvtailor.config import Config, ConfigError, ResumeConfig
from cvtailor.docmodel import has_suggestions, load_doc
from cvtailor.facts import FactsFile, RoleMapError, check_facts
from cvtailor.google_api import AuthRequired, GoogleClient
from cvtailor.models import Op, ParseError
from cvtailor.naming import doc_name, pick_folder, run_dir_name
from cvtailor.packs import analyze_pack, extract_pack, review_pack, route_pack, tailor_pack
from cvtailor.parse import parse_resume
from cvtailor.report import ReportData, review_md, summary_txt
from cvtailor.requests import build_requests
from cvtailor.reviewer import resolve_reviewer, run_review
from cvtailor.schemas import AiPlan, Analysis, Review, Route, Vacancy
from cvtailor.validate import PlanContext, make_context, split_valid, validate_ops
from cvtailor.verify import verify_applied

STEPS = ["extract", "route", "copy", "analyze", "tailor", "review", "apply", "report", "done"]
AI_FILES = {
    "extract": ("extract.md", "extract.pack.md", "vacancy.json"),
    "route": ("route.md", "route.pack.md", "route.json"),
    "analyze": ("analyze.md", "analyze.pack.md", "analysis.json"),
    "tailor": ("tailor.md", "tailor.pack.md", "plan_ai.json"),
}
MAX_REISSUES = 3
AUTH_TEXT = "Google sign-in is required: run `cvtailor login` (it opens a browser), then run `cvtailor next` again."


class Action(BaseModel):
    action: Literal["ai", "ask_user", "say", "auth", "done", "continue"]
    step: str
    prompt: str | None = None
    input: str | None = None
    output: str | None = None
    errors: list[CheckError] = []
    question: str | None = None
    options: list[str] = []
    text: str | None = None


class RunState(BaseModel):
    run_dir: str
    company: str
    created: str
    forced_resume: str | None = None
    resume_id: str | None = None
    step: str = "extract"
    awaiting: str | None = None
    reissues: int = 0
    attempts: dict[str, int] = {}
    errors: list[CheckError] = []
    blocked: str | None = None
    options: list[str] = []
    question: str | None = None
    folder_id: str | None = None
    copy_id: str | None = None
    copy_name: str | None = None
    copy_url: str | None = None
    copy_revision: str | None = None
    review_round: int = 0
    notes: list[str] = []
    apply_started: bool = False
    applied: bool = False

    @property
    def path(self) -> Path:
        return Path(self.run_dir)

    @classmethod
    def load(cls, run_dir: Path) -> "RunState":
        return cls.model_validate_json((Path(run_dir) / "state.json").read_text())

    def save(self) -> None:
        (self.path / "state.json").write_text(self.model_dump_json(indent=2))


@dataclass
class Deps:
    repo: Path
    cfg: Config
    resumes: list[ResumeConfig]
    facts: FactsFile
    client_factory: Callable[[], GoogleClient]
    reviewer_run: Callable = subprocess.run
    which: Callable[[str], str | None] = shutil.which
    today: date = field(default_factory=date.today)


def init_run(repo: Path, company: str, vacancy_text: str, forced_resume: str | None,
             resumes: list[ResumeConfig], today: date) -> RunState:
    if forced_resume and forced_resume not in {r.id for r in resumes}:
        raise ConfigError(f"unknown resume {forced_resume!r}; known: {[r.id for r in resumes]}")
    if not vacancy_text.strip():
        raise ConfigError("vacancy text is empty (pass it on stdin)")
    runs = repo / "runs"
    runs.mkdir(exist_ok=True)
    name = run_dir_name(company, today, {p.name for p in runs.iterdir()})
    run = runs / name
    run.mkdir()
    (run / "vacancy.txt").write_text(vacancy_text)
    state = RunState(run_dir=str(run), company=company, created=today.isoformat(), forced_resume=forced_resume)
    state.save()
    (runs / ".current").write_text(name)
    return state


class RunLocked(Exception):
    pass


LOCKED_TEXT = ("another cvtailor process is working on this run (a terminal or another chat session); "
               "wait for it to finish, then run the command again")


@contextmanager
def run_lock(run_dir: Path):
    """One process per run: a second `run`/`next` on the same folder stops instead of racing."""
    with open(Path(run_dir) / ".lock", "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RunLocked(LOCKED_TEXT) from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


class _Blocked(Exception):
    def __init__(self, text: str):
        self.text = text


class Runner:
    def __init__(self, state: RunState, deps: Deps):
        self.s, self.d = state, deps
        self._client: GoogleClient | None = None
        self._ctx: PlanContext | None = None

    # --- helpers -----------------------------------------------------------------
    @property
    def run(self) -> Path:
        return self.s.path

    def client(self) -> GoogleClient:
        if self._client is None:
            self._client = self.d.client_factory()
        return self._client

    def resume_cfg(self) -> ResumeConfig:
        return next(r for r in self.d.resumes if r.id == self.s.resume_id)

    def read(self, name: str):
        return json.loads((self.run / name).read_text())

    def write(self, name: str, obj) -> None:
        (self.run / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2))

    def copy_resume(self):
        return parse_resume(self.read("copy.json"), self.resume_cfg().editable_companies)

    def ctx(self) -> PlanContext:
        if self._ctx is None:
            rc = self.resume_cfg()
            self._ctx = make_context(self.copy_resume(), self.d.facts, rc.id, self.d.cfg.limits, rc.role_map)
        return self._ctx

    def vacancy(self) -> Vacancy:
        return Vacancy.model_validate(self.read("vacancy.json"))

    def ops(self) -> list[Op]:
        return [Op(**o) for o in self.read("plan.json")["ops"]]

    def advance(self, step: str) -> None:
        self.s.step = step
        self.s.awaiting = None
        self.s.reissues = 0
        self.s.errors = []
        self.s.save()

    # --- AI step protocol --------------------------------------------------------
    def ai(self, step: str, pack: Callable[[], str], model, judge: Callable) -> Action | None:
        prompt, pack_name, out_name = AI_FILES[step]
        out = self.run / out_name

        def issue(errors: list[CheckError]) -> Action:
            self.s.errors = errors
            text = pack()
            (self.run / pack_name).write_text(text)
            self.s.awaiting = step
            self.s.save()
            return Action(action="ai", step=step, prompt=str(self.d.repo / "prompts" / prompt),
                          input=str(self.run / pack_name), output=str(out), errors=errors)

        if self.s.awaiting != step:
            if out.exists():
                out.rename(self._free(out, "stale"))
            self.s.reissues = 0
            return issue(self.s.errors)  # empty, except reviewer findings handed back to tailor
        if not out.exists():
            self.s.reissues += 1
            if self.s.reissues > MAX_REISSUES:
                raise _Blocked(f"{step}: the agent did not write {out.name}")
            return issue(self.s.errors)
        obj, errors = load_ai_json(out, model)
        if obj is not None:
            # the answer may carry prose or code fences around the JSON: keep only the parsed object
            out.write_text(obj.model_dump_json(indent=2))
            result, errors = judge(obj)
            if not errors:
                self.s.awaiting = None
                return result
        n = self.s.attempts.get(step, 0) + 1
        self.s.attempts[step] = n
        out.rename(self._free(out, "attempt"))
        if n > self.d.cfg.max_ai_retries:
            return self.exhausted(step, errors)
        self.s.reissues = 0
        return issue(errors)

    def _free(self, path: Path, tag: str) -> Path:
        n = 1
        while path.with_name(f"{path.name}.{tag}{n}").exists():
            n += 1
        return path.with_name(f"{path.name}.{tag}{n}")

    def exhausted(self, step: str, errors: list[CheckError]) -> Action | None:
        prev = self.run / f"plan.round{self.s.review_round - 1}.json"
        if step == "tailor" and self.s.review_round and prev.exists():
            # the fix round failed validation: keep the plan that was valid and already reviewed
            (self.run / "plan.json").write_text(prev.read_text())
            old = self.read(f"review.round{self.s.review_round - 1}.json")
            old["status"] += "; fix round rejected by validators, reviewed plan kept"
            self.write("review.json", old)
            self.advance("apply")
            return None
        if step == "tailor" and (self.run / "ops_last.json").exists():
            ops = [Op(**o) for o in self.read("ops_last.json")]
            kept, dropped = split_valid(ops, self.ctx())
            if kept:
                self.save_plan(kept, dropped)
                self.advance("review")
                return None
        detail = "; ".join(f"{e.rule}: {e.detail}" for e in errors[:5])
        raise _Blocked(f"{step}: AI output still invalid after {self.d.cfg.max_ai_retries} retries ({detail}). "
                       f"Fix the cause and run `cvtailor next --from {step}`.")

    def save_plan(self, kept: list[Op], dropped: list[tuple[Op, list[CheckError]]]) -> None:
        self.write("plan.json", {"resume_id": self.s.resume_id, "base_revision": self.s.copy_revision,
                                 "ops": [o.model_dump() for o in kept]})
        if self.s.review_round and not dropped:
            return  # a fix round keeps the ops dropped before the first review
        self.write("dropped.json", [{"op": o.model_dump(), "errors": [e.model_dump() for e in errs]}
                                    for o, errs in dropped])

    # --- steps ---------------------------------------------------------------------
    def step_extract(self, answer):
        text = (self.run / "vacancy.txt").read_text()

        def judge(v: Vacancy):
            v, errs = check_vacancy(v, self.d.facts)
            if not errs:
                self.write("vacancy.json", v.model_dump())
                self.advance("route")
            return None, errs

        return self.ai("extract", lambda: extract_pack(text), Vacancy, judge)

    def step_route(self, answer):
        ids = [r.id for r in self.d.resumes]
        if self.s.forced_resume or len(ids) == 1:
            self.s.resume_id = self.s.forced_resume or ids[0]
            self.advance("copy")
            return None
        if self.s.options:
            choice = None
            if answer:
                a = answer.strip()
                if a in self.s.options:
                    choice = a
                elif a.isdigit() and 1 <= int(a) <= len(self.s.options):
                    choice = self.s.options[int(a) - 1]
            if choice:
                self.s.resume_id, self.s.options = choice, []
                self.advance("copy")
                return None
            note = f" (answer {answer!r} is not one of the options)" if answer else ""
            return Action(action="ask_user", step="route", question=(self.s.question or "") + note, options=self.s.options)

        def pack() -> str:
            if not (self.run / "route_resumes.json").exists():
                items = []
                for r in self.d.resumes:
                    parsed = parse_resume(self.client().get_doc(r.doc_id), r.editable_companies)
                    summary = next((b.text for b in parsed.blocks if b.kind == "summary"), "")
                    items.append({"cfg": r.model_dump(), "summary": summary})
                self.write("route_resumes.json", items)
            items = self.read("route_resumes.json")
            return route_pack(self.vacancy(), [(ResumeConfig(**i["cfg"]), i["summary"]) for i in items])

        def judge(r: Route):
            errs = check_route(r, ids)
            if errs:
                return None, errs
            if r.confidence == "high":
                self.s.resume_id = r.choice
                self.advance("copy")
                return None, []
            self.s.options = r.ranking[:2]
            self.s.question = (f"Which base resume should be tailored? {r.reason} "
                               f"Options: 1) {self.s.options[0]}  2) {self.s.options[1]}")
            self.s.save()
            return Action(action="ask_user", step="route", question=self.s.question, options=self.s.options), []

        return self.ai("route", pack, Route, judge)

    def step_copy(self, answer):
        rc, client, cfg = self.resume_cfg(), self.client(), self.d.cfg
        if not self.s.copy_id:
            if not self.s.folder_id:
                folders = client.list_folders(cfg.output_folder_id)
                self.s.folder_id = pick_folder(self.s.company, folders) or client.create_folder(self.s.company, cfg.output_folder_id)
                self.s.save()
            name = doc_name(rc.label, self.s.company, date.fromisoformat(self.s.created), client.list_doc_names(self.s.folder_id))
            self.s.copy_id = client.copy_doc(rc.doc_id, name, self.s.folder_id)
            self.s.copy_name = name
            self.s.copy_url = f"https://docs.google.com/document/d/{self.s.copy_id}/edit"
            self.s.save()
        doc = client.get_doc(self.s.copy_id)
        self.write("copy.json", doc)
        try:
            resume = parse_resume(doc, rc.editable_companies)
        except ParseError as exc:
            raise _Blocked(f"copy: cannot parse the resume copy: {exc}")
        self.write("blocks.json", resume.model_dump())
        self.s.copy_revision = doc.get("revisionId")
        report = check_facts(self.d.facts, {rc.id: resume}, partial=True)
        if report.problems:
            raise _Blocked("copy: facts.json problems for this resume (run `cvtailor facts check`):\n- "
                           + "\n- ".join(report.problems[:10]))
        self._ctx = None
        try:
            self.ctx()
        except RoleMapError as exc:
            raise _Blocked(f"copy: {exc}")
        self.advance("analyze")
        return None

    def step_analyze(self, answer):
        def judge(a: Analysis):
            errs = check_analysis(a, self.ctx().resume, self.d.facts)
            if not errs:
                self.advance("tailor")
            return None, errs

        return self.ai("analyze", lambda: analyze_pack(self.vacancy(), self.ctx()), Analysis, judge)

    def step_tailor(self, answer):
        analysis = Analysis.model_validate(self.read("analysis.json"))

        def judge(raw: AiPlan):
            ops, errs = parse_plan_ops(raw)
            self.write("ops_last.json", [o.model_dump() for o in ops])
            errs = errs + validate_ops(ops, self.ctx())
            if not errs:
                self.save_plan(ops, [])
                self.advance("review")
            return None, errs

        return self.ai("tailor", lambda: tailor_pack(self.vacancy(), analysis, self.ctx(), self.s.errors),
                       AiPlan, judge)

    def step_review(self, answer):
        ops = self.ops()
        if not ops:
            from cvtailor.models import VerifyReport
            self.write("review.json", {"status": "none: no edits", "review": None})
            self.write("verify.json", VerifyReport(ok=True, problems=[]).model_dump())
            self.advance("report")
            return None
        command = resolve_reviewer(self.d.cfg, self.d.which)
        prompt = (self.d.repo / "prompts" / "review.md").read_text()
        review, status = run_review(command, prompt, review_pack(ops, self.ctx()), [o.id for o in ops],
                                    self.d.cfg.reviewer_timeout_s, run=self.d.reviewer_run)
        flagged = [v for v in review.verdicts if v.verdict != "supported"] if review else []
        if self.s.review_round:
            status += f" (after {self.s.review_round} fix round{'s' if self.s.review_round > 1 else ''})"
        self.write("review.json", {"status": status, "review": review.model_dump() if review else None})
        if flagged and self.s.review_round < self.d.cfg.review_fix_rounds:
            return self.hand_back_to_tailor(flagged)
        self.advance("apply")
        return None

    def hand_back_to_tailor(self, flagged) -> None:
        """Reviewer findings go back to tailor as errors; the fixed plan is validated and reviewed again."""
        n = self.s.review_round
        shutil.copyfile(self.run / "plan.json", self.run / f"plan.round{n}.json")
        shutil.copyfile(self.run / "review.json", self.run / f"review.round{n}.json")
        out = self.run / AI_FILES["tailor"][2]
        if out.exists():
            out.rename(self._free(out, "attempt"))  # the previous answer the retry instructions point to
        errors = [CheckError(rule="review", op=v.op,
                             detail=f"independent fact checker: {v.verdict}, «{v.quote}» — {v.comment}".rstrip(" —"))
                  for v in flagged]
        self.s.review_round = n + 1
        self.s.attempts.pop("tailor", None)
        self.advance("tailor")
        self.s.errors = errors
        self.s.save()
        return None

    def step_apply(self, answer):
        client, ops = self.client(), self.ops()
        if not self.s.applied:
            doc = client.get_doc(self.s.copy_id)
            if self.s.apply_started and has_suggestions(doc):
                self.s.applied = True
                self.s.save()
            else:
                resume = self.ctx().resume
                if doc.get("revisionId") != self.s.copy_revision:
                    try:
                        now = parse_resume(doc, self.resume_cfg().editable_companies)
                    except ParseError:
                        now = None
                    if now is None or [(b.id, b.sha) for b in now.blocks] != [(b.id, b.sha) for b in resume.blocks]:
                        raise _Blocked("apply: the copy was edited after analysis; "
                                       "run `cvtailor next --from analyze` to plan again on the current text")
                    self.s.copy_revision = doc.get("revisionId")
                    resume = now
                body = build_requests(resume, ops)
                self.s.apply_started = True
                self.s.save()
                client.batch_update(self.s.copy_id, body)
                self.s.applied = True
                self.s.save()
        before = self.read("copy.json")
        preview = client.get_doc(self.s.copy_id, preview_accepted=True)
        self.write("after.json", preview)
        report = verify_applied(before, preview, self.ctx().resume, ops)
        self.write("verify.json", report.model_dump())
        if not report.ok and not (self.s.copy_name or "").startswith("[FAILED]"):
            failed = f"[FAILED] {self.s.copy_name}"
            client.rename(self.s.copy_id, failed)
            self.s.copy_name = failed
        self.advance("report")
        return None

    def step_report(self, answer):
        from cvtailor.models import VerifyReport
        review_raw = self.read("review.json")
        route = Route.model_validate(self.read("route.json")) if (self.run / "route.json").exists() else None
        dropped = [(Op(**d["op"]), [CheckError(**e) for e in d["errors"]]) for d in self.read("dropped.json")]
        data = ReportData(
            vacancy=self.vacancy(), resume_label=self.resume_cfg().label, route=route, doc_url=self.s.copy_url or "",
            analysis=Analysis.model_validate(self.read("analysis.json")), applied=self.ops(), dropped=dropped,
            resume=self.ctx().resume, facts=self.d.facts,
            review=Review.model_validate(review_raw["review"]) if review_raw["review"] else None,
            reviewer_status=review_raw["status"], verify=VerifyReport.model_validate(self.read("verify.json")),
            notes=self.s.notes,
        )
        (self.run / "review.md").write_text(review_md(data))
        text = summary_txt(data)
        (self.run / "summary.txt").write_text(text)
        self.advance("done")
        return Action(action="say", step="report", text=text)

    def step_done(self, answer):
        return Action(action="done", step="done", text=f"Run finished: {self.s.copy_url}")

    # --- entry ----------------------------------------------------------------------
    def reset(self, from_step: str) -> Action | None:
        if from_step not in STEPS:
            return Action(action="say", step=self.s.step, text=f"unknown step {from_step!r}; steps: {STEPS}")
        target = "copy" if from_step == "analyze" else from_step
        if STEPS.index(target) > STEPS.index(self.s.step):
            return Action(action="say", step=self.s.step,
                          text=f"step {from_step!r} is ahead of the current step {self.s.step!r}; run `cvtailor next`")
        if self.s.apply_started and STEPS.index(target) <= STEPS.index("apply"):
            return Action(action="say", step=self.s.step,
                          text="edits were already applied to this copy; start a new run with `cvtailor init`")
        if STEPS.index(target) <= STEPS.index("route") and self.s.copy_id:
            # the resume may change: the old copy stays in Drive, a new one will be made
            self.s.copy_id = self.s.copy_name = self.s.copy_url = self.s.copy_revision = None
        for name in ("ops_last.json",):
            if STEPS.index(target) <= STEPS.index("tailor") and (self.run / name).exists():
                (self.run / name).rename(self._free(self.run / name, "stale"))
        for st in STEPS[STEPS.index(target):]:
            self.s.attempts.pop(st, None)
        if STEPS.index(target) <= STEPS.index("tailor"):
            self.s.review_round = 0
        if STEPS.index(target) <= STEPS.index("route"):
            self.s.options, self.s.question = [], None
            self.s.resume_id = self.s.forced_resume
        self.s.blocked = None
        self._ctx = None
        self.advance(target)
        return None

    def next(self, answer: str | None = None, from_step: str | None = None) -> Action:
        if from_step:
            act = self.reset(from_step)
            if act:
                return act
        if self.s.blocked:
            return Action(action="say", step=self.s.step, text=self.s.blocked)
        try:
            for _ in range(len(STEPS) * 2):
                act = getattr(self, f"step_{self.s.step}")(answer)
                answer = None if self.s.step != "route" else answer
                if act is not None:
                    self.s.save()
                    return act
            raise RuntimeError("state machine did not stop")
        except AuthRequired:
            self.s.save()
            return Action(action="auth", step=self.s.step, text=AUTH_TEXT)
        except _Blocked as blk:
            self.s.blocked = blk.text
            self.s.save()
            return Action(action="say", step=self.s.step, text=blk.text)
        except Exception as exc:  # keep the one-JSON-line contract; the step will be retried
            self.s.save()
            return Action(action="say", step=self.s.step,
                          text=f"{self.s.step}: {type(exc).__name__}: {exc}. Run `cvtailor next` to retry.")


def next_action(state: RunState, deps: Deps, answer: str | None = None, from_step: str | None = None) -> Action:
    return Runner(state, deps).next(answer, from_step)
