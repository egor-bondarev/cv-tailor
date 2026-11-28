import json

import pytest
import yaml

import cvtailor.cli as cli
from cvtailor.config import ConfigError, load_config, load_resumes
from test_facts import facts_data


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "facts.json").write_text(json.dumps(facts_data()))
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"output_folder_id": "out"}))
    (tmp_path / "resumes.yaml").write_text(yaml.safe_dump([
        {"id": "cv", "label": "SDET", "doc_id": "doc-1", "target_role": "SDET", "editable_companies": ["acme"]},
    ]))
    return tmp_path


def test_load_config_defaults(repo):
    cfg = load_config(repo)
    assert cfg.output_folder_id == "out" and cfg.facts_path == "docs/facts.json"


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="config.yaml"):
        load_config(tmp_path)


def test_load_resumes(repo):
    [r] = load_resumes(repo)
    assert r.id == "cv" and r.editable_companies == ["acme"]


def test_facts_check_offline_ok(repo, capsys):
    assert cli.main(["facts", "check", "--offline", "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "4 facts, 4 verified" in out and "OK" in out


def test_facts_check_reports_problems(repo, capsys):
    data = facts_data()
    data["facts"][0]["role_id"] = "nope"
    (repo / "docs" / "facts.json").write_text(json.dumps(data))
    assert cli.main(["facts", "check", "--offline", "--repo", str(repo)]) == 1
    assert "unknown role" in capsys.readouterr().out


def test_facts_check_online_uses_resumes(repo, capsys, monkeypatch, resume_doc):
    class Client:
        def get_doc(self, doc_id):
            assert doc_id == "doc-1"
            return resume_doc

    monkeypatch.setattr(cli, "make_client", lambda repo_dir, cfg, resumes: Client())
    assert cli.main(["facts", "check", "--repo", str(repo)]) == 0
    assert "checked against 1 resumes" in capsys.readouterr().out


def test_facts_check_online_quote_problem(repo, capsys, monkeypatch, resume_doc):
    data = facts_data()
    data["facts"][0]["used_in"][0]["quote"] = "Missing quote"
    (repo / "docs" / "facts.json").write_text(json.dumps(data))
    monkeypatch.setattr(cli, "make_client", lambda repo_dir, cfg, resumes: type("C", (), {"get_doc": lambda self, d: resume_doc})())
    assert cli.main(["facts", "check", "--repo", str(repo)]) == 1
    assert "quote not found" in capsys.readouterr().out


def test_usage_without_args(capsys):
    assert cli.main([]) == 2


def test_config_limits_defaults_and_override(repo):
    assert load_config(repo).limits.bullet_max_chars == 220
    (repo / "config.yaml").write_text(yaml.safe_dump({"output_folder_id": "out", "limits": {"bullet_max_chars": 200}}))
    cfg = load_config(repo)
    assert cfg.limits.bullet_max_chars == 200 and cfg.limits.max_ops_per_plan == 12
    assert cfg.reviewer_command == ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-"]


def test_resume_role_map_field(repo):
    (repo / "resumes.yaml").write_text(yaml.safe_dump([{"id": "cv", "label": "L", "doc_id": "d", "role_map": {"acme/x": "r"}}]))
    assert load_resumes(repo)[0].role_map == {"acme/x": "r"}


def _setup_run_repo(repo):
    from test_state import facts_obj
    (repo / "docs" / "facts.json").write_text(facts_obj().model_dump_json())
    (repo / "prompts").mkdir(exist_ok=True)


def test_init_creates_run_and_current(repo, monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("We need an SDET"))
    assert cli.main(["init", "--company", "Acme", "--repo", str(repo)]) == 0
    name = (repo / "runs" / ".current").read_text()
    assert (repo / "runs" / name / "vacancy.txt").read_text() == "We need an SDET"
    assert name in capsys.readouterr().out


def test_init_unknown_resume_errors(repo, monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("text"))
    assert cli.main(["init", "--company", "Acme", "--resume", "nope", "--repo", str(repo)]) == 1
    assert "unknown resume" in capsys.readouterr().out


def test_next_prints_single_json_line(repo, monkeypatch, capsys):
    import io
    _setup_run_repo(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO("We need an SDET"))
    cli.main(["init", "--company", "Acme", "--repo", str(repo)])
    capsys.readouterr()
    assert cli.main(["next", "--repo", str(repo)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and json.loads(out[0])["action"] == "ai"


def test_final_without_copy_says_so(repo, monkeypatch, capsys):
    import io
    _setup_run_repo(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO("We need an SDET"))
    cli.main(["init", "--company", "Acme", "--repo", str(repo)])
    capsys.readouterr()
    assert cli.main(["final", "--repo", str(repo)]) == 1
    assert "no copy" in capsys.readouterr().out


def test_run_json_starts_run_and_prints_one_line(repo, monkeypatch, capsys):
    import io
    from cvtailor.ai import CallRecord
    _setup_run_repo(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO("We need an SDET"))
    monkeypatch.setattr("cvtailor.autorun.call_model",
                        lambda step, *a: CallRecord(step=step, model="m", ok=False, error="exit 1"))
    assert cli.main(["run", "--company", "Acme", "--json", "--repo", str(repo)]) == 0
    captured = capsys.readouterr()
    out = captured.out.strip().splitlines()
    assert len(out) == 1 and "extract: AI call failed" in json.loads(out[0])["text"]
    assert "[cvtailor] extract: calling the model" in captured.err
    assert (repo / "runs" / (repo / "runs" / ".current").read_text() / "ai_calls.jsonl").exists()


def _fake_fetch(monkeypatch, company="Acme"):
    from cvtailor.fetch import FetchError, Page

    def fetch(url):
        if "fail" in url:
            raise FetchError("the site answered HTTP 403")
        return Page(url=url + "?final", html="<html>page</html>", text="Role: SDET\n\nWe need an SDET", company=company)
    monkeypatch.setattr("cvtailor.fetch.fetch_vacancy", fetch)


def test_init_from_url_takes_company_from_page(repo, monkeypatch, capsys):
    import io
    _fake_fetch(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cli.main(["init", "--url", "https://jobs.example.com/1", "--repo", str(repo)]) == 0
    run = repo / "runs" / (repo / "runs" / ".current").read_text()
    assert run.name.endswith("_acme")
    assert (run / "vacancy.txt").read_text() == "Role: SDET\n\nWe need an SDET"
    assert (run / "vacancy.url").read_text() == "https://jobs.example.com/1?final\n"
    assert (run / "vacancy.html").read_text() == "<html>page</html>"


def test_init_from_url_with_text_on_stdin_does_not_fetch(repo, monkeypatch):
    import io
    monkeypatch.setattr("cvtailor.fetch.fetch_vacancy", lambda url: pytest.fail("must not fetch"))
    monkeypatch.setattr("sys.stdin", io.StringIO("Text read by the agent"))
    assert cli.main(["init", "--url", "https://x.example.com/1", "--company", "Globex", "--repo", str(repo)]) == 0
    run = repo / "runs" / (repo / "runs" / ".current").read_text()
    assert (run / "vacancy.txt").read_text() == "Text read by the agent"
    assert (run / "vacancy.url").exists() and not (run / "vacancy.html").exists()


def test_init_from_url_without_company_errors(repo, monkeypatch, capsys):
    import io
    _fake_fetch(monkeypatch, company=None)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cli.main(["init", "--url", "https://jobs.example.com/1", "--repo", str(repo)]) == 1
    assert "company name not found on the page: pass --company" in capsys.readouterr().out
    assert not (repo / "runs" / ".current").exists()


def test_run_json_unreadable_page_says_how_to_continue(repo, monkeypatch, capsys):
    import io
    _setup_run_repo(repo)
    _fake_fetch(monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cli.main(["run", "--url", "https://fail.example.com/1", "--json", "--repo", str(repo)]) == 1
    act = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert act["action"] == "say" and "HTTP 403" in act["text"] and "same --url" in act["text"]


def test_init_needs_company_or_url(repo):
    with pytest.raises(SystemExit):
        cli.main(["init", "--repo", str(repo)])


def test_letter_before_the_resume_is_done_says_so(repo, monkeypatch, capsys):
    import io
    _setup_run_repo(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO("We need an SDET"))
    cli.main(["init", "--company", "Acme", "--repo", str(repo)])
    capsys.readouterr()
    assert cli.main(["letter", "--short", "--repo", str(repo)]) == 1
    assert "not finished" in capsys.readouterr().out


def test_letter_no_run_saves_the_request(repo, monkeypatch, capsys):
    import io
    from cvtailor.state import RunState
    _setup_run_repo(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO("We need an SDET"))
    cli.main(["init", "--company", "Acme", "--repo", str(repo)])
    run = repo / "runs" / (repo / "runs" / ".current").read_text()
    s = RunState.load(run)
    s.step, s.applied = "done", True
    s.save()
    assert cli.main(["letter", "--feedback", "shorter intro", "--max-chars", "900", "--no-run",
                     "--repo", str(repo)]) == 0
    s = RunState.load(run)
    assert s.letter_feedback == ["shorter intro"] and s.letter_max_chars == 900 and s.letter_revise
    assert cli.main(["letter", "--short", "--no-run", "--repo", str(repo)]) == 0
    s = RunState.load(run)
    assert s.letter_mode == "short" and s.letter_max_chars is None and s.letter_feedback == ["shorter intro"]


def test_letter_max_chars_too_small(repo):
    with pytest.raises(SystemExit):
        cli.main(["letter", "--max-chars", "100", "--repo", str(repo)])


def test_export_pdfs_uploads_then_replaces(tmp_path):
    from cvtailor.profile import Profile
    from cvtailor.state import RunState

    (tmp_path / "vacancy.json").write_text(json.dumps({
        "title": "Senior SDET", "language": "en", "summary": "s", "must_have": ["Python"]}))
    state = RunState(run_dir=str(tmp_path), company="Acme", created="2026-11-28", copy_id="copy-1",
                     copy_name="SDET - Acme", folder_id="folder-1", letter_id="letter-1", letter_name="CL")

    class Client:
        def __init__(self):
            self.uploads = []

        def export_pdf(self, file_id):
            return f"pdf of {file_id}".encode()

        def upload_pdf(self, name, parent, data, file_id=None):
            self.uploads.append((name, data, file_id))
            return file_id or f"pdf-{len(self.uploads)}"

    deps = type("D", (), {"profile": Profile.model_validate({"contacts": {"name": "Jane Doe"}})})()
    client = Client()
    text = cli.export_pdfs(client, state, deps)
    assert client.uploads == [("Jane Doe. Resume - Senior SDET.pdf", b"pdf of copy-1", None),
                              ("Jane Doe. Cover Letter - Senior SDET.pdf", b"pdf of letter-1", None)]
    assert RunState.load(tmp_path).pdf_ids == {"resume": "pdf-1", "letter": "pdf-2"}
    assert "Jane Doe. Resume - Senior SDET.pdf" in text
    cli.export_pdfs(client, state, deps)
    assert [u[2] for u in client.uploads[2:]] == ["pdf-1", "pdf-2"]
