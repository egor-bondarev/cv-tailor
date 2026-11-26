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
