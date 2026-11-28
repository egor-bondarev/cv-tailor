"""Local configuration: config.yaml and resumes.yaml (DESIGN.md §13)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from cvtailor.ai import AiSettings


class ConfigError(ValueError):
    pass


class Limits(BaseModel):
    bullet_max_chars: int = 220
    bullet_replace_max_ratio: float = 1.15
    intro_max_ratio: float = 1.15
    summary_min_ratio: float = 0.80
    summary_max_ratio: float = 1.15
    title_max_chars: int = 80
    skills_line_max_ratio: float = 1.20
    max_bullets_per_role: int = 10
    max_ops_per_plan: int = 12
    max_ops_per_past_company: int = 1
    total_editable_max_ratio: float = 1.05


class CoverLetterSettings(BaseModel):
    enabled: bool = True
    mode: Literal["full", "short"] = "full"
    export_pdf: bool = True  # `final` exports the resume and the letter to PDF in the company folder
    header: bool = False  # contacts above the letter (for a PDF attachment); the name always signs it


class Config(BaseModel):
    model_config = ConfigDict(extra="allow")
    output_folder_id: str
    facts_path: str = "docs/facts.json"
    second_reviewer: str = "auto"
    max_ai_retries: int = 2
    limits: Limits = Limits()
    reviewer_command: list[str] = ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-"]
    reviewer_timeout_s: int = 100
    review_fix_rounds: int = 1
    doc_comments: bool = True
    ai: AiSettings = AiSettings()
    profile_path: str = "profile.yaml"
    cover_letter: CoverLetterSettings = CoverLetterSettings()


class ResumeConfig(BaseModel):
    id: str
    label: str
    doc_id: str
    target_role: str = ""
    # list: these companies are priority 1, later EXPERIENCE companies get 2, 3, …;
    # empty: the two most recent companies are priority 1; dict: explicit priorities (0 = read-only)
    editable_companies: list[str] | dict[str, int] = []
    role_map: dict[str, str] = {}


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
