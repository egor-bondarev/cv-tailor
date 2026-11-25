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
