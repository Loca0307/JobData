from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    field_validator,
)

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
TARGET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class CompanyTargetBase(BaseModel):
    """Configuration shared by every company career-site target."""

    model_config = ConfigDict(extra="forbid")

    id: str
    company_name: str = Field(min_length=1, max_length=300)
    careers_url: HttpUrl

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not TARGET_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "id must contain lowercase letters, numbers, and hyphens"
            )
        return value

    @property
    def source_name(self) -> str:
        return f"company:{self.id}"


class GreenhouseTarget(CompanyTargetBase):
    ats: Literal["greenhouse"]
    board_token: str

    @field_validator("board_token")
    @classmethod
    def validate_board_token(cls, value: str) -> str:
        if not TOKEN_PATTERN.fullmatch(value):
            raise ValueError("board_token must be a Greenhouse board token")
        return value


class LeverTarget(CompanyTargetBase):
    ats: Literal["lever"]
    site: str
    region: Literal["global", "eu"] = "global"

    @field_validator("site")
    @classmethod
    def validate_site(cls, value: str) -> str:
        if not TOKEN_PATTERN.fullmatch(value):
            raise ValueError("site must be a Lever site token")
        return value


CompanyTarget = Annotated[
    GreenhouseTarget | LeverTarget,
    Field(discriminator="ats"),
]


class CompanyTargetCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: list[CompanyTarget] = Field(default_factory=list)


def load_company_target_catalog(path: Path) -> CompanyTargetCatalog:
    """Load and validate the complete catalog before any network work starts."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        catalog = CompanyTargetCatalog.model_validate(payload)
    except OSError as exc:
        raise ValueError(f"Cannot read company target catalog {path}: {exc}") from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"Invalid company target catalog {path}: {exc}") from exc

    ids = [target.id for target in catalog.targets]
    duplicates = sorted({target_id for target_id in ids if ids.count(target_id) > 1})
    if duplicates:
        raise ValueError(
            "Duplicate company target ids: " + ", ".join(duplicates)
        )
    return catalog
