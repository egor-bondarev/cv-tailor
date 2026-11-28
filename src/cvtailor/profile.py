"""Private candidate profile for cover letters: contacts, motivation, relocation (v2 V6).

Contacts stay local: Python puts them in the letter header, they never go to a model.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from cvtailor.config import ConfigError

_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Contacts(_Strict):
    name: str = ""
    email: str = ""
    phone: str = ""
    linkedin: str = ""


class Motivation(_Strict):
    id: str
    text: str

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _ID.match(v):
            raise ValueError("use lowercase letters, digits and hyphens")
        return v


class Relocation(_Strict):
    base: str
    text: str = "open to relocation"


class Profile(_Strict):
    contacts: Contacts = Contacts()
    motivation: list[Motivation] = []
    relocation: Relocation | None = None

    @field_validator("motivation")
    @classmethod
    def _unique(cls, items: list[Motivation]) -> list[Motivation]:
        seen = [m.id for m in items]
        dup = sorted({i for i in seen if seen.count(i) > 1})
        if dup:
            raise ValueError(f"duplicate motivation ids: {dup}")
        return items

    @property
    def motivation_ids(self) -> set[str]:
        return {m.id for m in self.motivation}

    def header(self) -> str:
        c = self.contacts
        details = " | ".join(x.strip() for x in (c.email, c.phone, c.linkedin) if x.strip())
        return "\n".join(x for x in (c.name.strip(), details) if x)


def load_profile(path: Path) -> Profile | None:
    """None when the file does not exist: the letter is then written from the vacancy and the facts only."""
    if not path.exists():
        return None
    try:
        return Profile.model_validate(yaml.safe_load(path.read_text()) or {})
    except ValidationError as exc:
        err = exc.errors()[0]
        raise ConfigError(f"{path.name}: {'.'.join(map(str, err['loc']))}: {err['msg']}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name}: not valid YAML ({exc})") from None
