# noqa: CPY001
"""Common report and issue contracts for later remedy selection."""

from enum import StrEnum
import datetime  # noqa: TC003 - Pydantic resolves annotations at runtime
from pathlib import Path  # noqa: TC003 - Pydantic resolves annotations at runtime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReportType(StrEnum):
    """Explicit supported input formats."""

    REPOAUDITOR = "repoauditor"
    SCORECARD = "ossf-scorecard"


class Source(BaseModel):
    """Identity of the exact source bytes and selected scan."""

    path: Path
    sha256: str
    report_type: ReportType
    version: str | None = None
    audited_commit: str | None = None
    scan_date: datetime.datetime | datetime.date | None = None


class Issue(BaseModel):
    """Source-specific evidence; status is not a guarantee of a usable remedy."""

    model_config = ConfigDict(strict=True)
    origin: Literal["RA", "OSSF"]
    check: str
    status: Literal["warning", "error", "gap", "unavailable"]
    original_status: str | None = None
    evidence: str
    location: str
    score: int | None = None


class Report(BaseModel):
    """Issues whose locations refer to this source report."""

    repository: str
    source: Source
    issues: list[Issue]
    notices: list[str]
