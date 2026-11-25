"""Local configuration: config.yaml and resumes.yaml (DESIGN.md §13)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError


class ConfigError(ValueError):
    pass


class Config(BaseModel):
    model_config = ConfigDict(extra="allow")
    output_folder_id: str
    facts_path: str = "docs/facts.json"
    second_reviewer: str = "auto"
    max_ai_retries: int = 2


class ResumeConfig(BaseModel):
    id: str
    label: str
    doc_id: str
    target_role: str = ""
    editable_companies: list[str] = []


def _read_yaml(path: Path):
    if not path.exists():
        raise ConfigError(f"{path.name} not found in {path.parent}: copy {path.stem}.example.yaml and fill it in")
    return yaml.safe_load(path.read_text())


def load_config(repo: Path) -> Config:
    try:
        return Config.model_validate(_read_yaml(repo / "config.yaml") or {})
    except ValidationError as exc:
        raise ConfigError(f"config.yaml: {exc.errors()[0]['loc']}: {exc.errors()[0]['msg']}") from None


def load_resumes(repo: Path) -> list[ResumeConfig]:
    try:
        return [ResumeConfig.model_validate(r) for r in _read_yaml(repo / "resumes.yaml") or []]
    except ValidationError as exc:
        raise ConfigError(f"resumes.yaml: {exc.errors()[0]['loc']}: {exc.errors()[0]['msg']}") from None
