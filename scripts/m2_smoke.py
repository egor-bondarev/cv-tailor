"""M2 end-to-end smoke test against live Google.

  python scripts/m2_smoke.py parse                # parse every resume in resumes.yaml
  python scripts/m2_smoke.py apply <resume_id>    # copy, apply 4 edits as suggestions, verify
  python scripts/m2_smoke.py final <copy_id>      # after Accept all / Reject all in Docs

Artifacts: runs/_smoke/<copy_id>/
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import yaml

from cvtailor.google_api import AuthRequired, GoogleClient, login
from cvtailor.models import Op, ParseError
from cvtailor.naming import doc_name, pick_folder
from cvtailor.parse import parse_resume
from cvtailor.requests import build_requests
from cvtailor.verify import final_check, verify_applied

REPO = Path(__file__).resolve().parents[1]
SMOKE_DIR = REPO / "runs" / "_smoke"
SMOKE_FOLDER = "cv-tailor-smoke"


def load_config() -> tuple[dict, dict[str, dict]]:
    config = yaml.safe_load((REPO / "config.yaml").read_text())
    resumes = {r["id"]: r for r in yaml.safe_load((REPO / "resumes.yaml").read_text())}
    return config, resumes


def make_client(config: dict, resumes: dict[str, dict]) -> GoogleClient:
    allowed = {r["doc_id"] for r in resumes.values()}
    try:
        return GoogleClient.from_token(REPO, allowed, config["output_folder_id"])
    except AuthRequired as exc:
        print(f"{exc}; opening browser to sign in")
        login(REPO)
        return GoogleClient.from_token(REPO, allowed, config["output_folder_id"])


def doc_url(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/edit"


def cmd_parse(client: GoogleClient, resumes: dict[str, dict]) -> int:
    failed = 0
    for rid, r in resumes.items():
        try:
            parsed = parse_resume(client.get_doc(r["doc_id"]), r["editable_companies"])
        except ParseError as exc:
            failed += 1
            print(f"{rid}: ERROR {exc}")
            continue
        editable = sum(b.editable for b in parsed.blocks)
        print(f"{rid}: {len(parsed.blocks)} blocks, {editable} editable")
    return 1 if failed else 0


def smoke_ops(resume) -> list[Op]:
    roles: dict[tuple, list] = {}
    for b in resume.blocks:
        if b.kind == "bullet" and b.editable:
            roles.setdefault((b.company, b.role), []).append(b)
    bullets = next((bs for bs in roles.values() if len(bs) >= 3), None)
    if bullets is None:
        raise SystemExit("smoke needs a role with at least 3 editable bullets")
    skills = next(b for b in resume.blocks if b.kind == "skills" and b.editable)
    return [
        Op(id=1, op="replace", block=bullets[0].id, new_text="Smoke replaced bullet."),
        Op(id=2, op="insert_after", after=bullets[0].id, new_text="Smoke inserted bullet."),
        Op(id=3, op="delete", block=bullets[2].id),
        Op(id=4, op="replace_skills", block=skills.id, new_value="Smoke, Values"),
    ]


def cmd_apply(client: GoogleClient, config: dict, resume_cfg: dict) -> int:
    out = config["output_folder_id"]
    folder = pick_folder(SMOKE_FOLDER, client.list_folders(out)) or client.create_folder(SMOKE_FOLDER, out)
    name = doc_name("SMOKE " + resume_cfg["label"], "smoke", date.today(), client.list_doc_names(folder))
    copy = client.copy_doc(resume_cfg["doc_id"], name, folder)
    before = client.get_doc(copy)
    resume = parse_resume(before, resume_cfg["editable_companies"])
    ops = smoke_ops(resume)
    client.batch_update(copy, build_requests(resume, ops))
    preview = client.get_doc(copy, preview_accepted=True)
    report = verify_applied(before, preview, resume, ops)

    run = SMOKE_DIR / copy
    run.mkdir(parents=True, exist_ok=True)
    (run / "before.json").write_text(json.dumps(before))
    (run / "preview.json").write_text(json.dumps(preview))
    (run / "ops.json").write_text(json.dumps([o.model_dump() for o in ops], indent=1))
    (run / "meta.json").write_text(json.dumps({"resume_id": resume_cfg["id"], "url": doc_url(copy)}))

    print(doc_url(copy))
    print("OK" if report.ok else "PROBLEMS:\n  " + "\n  ".join(report.problems))
    return 0 if report.ok else 1


def cmd_final(client: GoogleClient, resumes: dict[str, dict], copy_id: str) -> int:
    run = SMOKE_DIR / copy_id
    meta = json.loads((run / "meta.json").read_text())
    resume_cfg = resumes[meta["resume_id"]]
    before = json.loads((run / "before.json").read_text())
    resume = parse_resume(before, resume_cfg["editable_companies"])
    report = final_check(before, client.get_doc(copy_id), resume, resume_cfg["editable_companies"])
    print("OK" if report.ok else "PROBLEMS:\n  " + "\n  ".join(report.problems))
    return 0 if report.ok else 1


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("parse", "apply", "final"):
        print(__doc__)
        return 2
    config, resumes = load_config()
    client = make_client(config, resumes)
    if argv[0] == "parse":
        return cmd_parse(client, resumes)
    if argv[0] == "apply":
        return cmd_apply(client, config, resumes[argv[1]])
    return cmd_final(client, resumes, argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
