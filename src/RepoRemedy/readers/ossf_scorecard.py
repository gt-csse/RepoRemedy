# noqa: CPY001
"""Read OpenSSF Scorecard v5 JSON, including audit-tool envelopes and scan arrays."""

import datetime
import json
from typing import Annotated, NoReturn

from pydantic import BaseModel, ConfigDict, Field, field_validator

from RepoRemedy.models import Issue, Report, Source
from RepoRemedy.readers.common import ReportError, repository_name

MAX_SCORE = 10
# Search for at least one non-whitespace character; reasons may contain spaces.
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]


class _Check(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")
    name: Text
    score: Annotated[int, Field(ge=-1, le=MAX_SCORE)]
    reason: Text


class _Repository(BaseModel):
    model_config = ConfigDict(strict=True)
    name: str
    commit: str | None = None


class _Version(BaseModel):
    # Only v5 exports are supported; new major versions need compatibility tests.
    version: Annotated[str, Field(pattern=r"^v5\.\d+\.\d+(?:[-+].+)?$")]


class _Scan(BaseModel):
    model_config = ConfigDict(strict=True)
    repo: _Repository
    scorecard: _Version
    checks: Annotated[list[_Check], Field(min_length=1)]
    date: datetime.datetime | datetime.date | None = None

    @field_validator("date", mode="before")
    @classmethod
    def _parse_date(cls, value: object) -> datetime.datetime | datetime.date | None:
        if value is None:
            return None
        if not isinstance(value, str):
            message = "Scan date must be an ISO date or datetime string"
            raise ValueError(message)  # noqa: TRY004 - Pydantic wraps ValueError, not TypeError
        if len(value) == 10:  # noqa: PLR2004 - YYYY-MM-DD exports retain date-only precision
            return datetime.date.fromisoformat(value)
        return datetime.datetime.fromisoformat(value)


def _invalid_constant(_value: str) -> NoReturn:
    """json.loads requires a callback to reject non-finite numeric literals."""
    message = "Non-finite JSON numbers are not supported"
    raise ReportError(message)


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len(dict(pairs)) != len(pairs):
        message = "Duplicate JSON object keys are ambiguous"
        raise ReportError(message)
    return dict(pairs)


def read_ossf_scorecard(text: str, repository: str, source: Source) -> Report:
    """Validate all supplied scans and require exactly one repository match."""
    data = json.loads(text, object_pairs_hook=_object, parse_constant=_invalid_constant)
    candidates = data if isinstance(data, list) else [data]
    matches = []
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            message = "Scorecard scans must be JSON objects"
            raise ReportError(message)
        wrapped = "meta" in item
        scan = _Scan.model_validate(item.get("scorecard") if wrapped else item)
        prefix = (f"/{index}" if isinstance(data, list) else "") + ("/scorecard" if wrapped else "")
        if repository_name(scan.repo.name) == repository:
            matches.append((scan, prefix))
    if len(matches) != 1:
        message = "Expected exactly one scan matching the repository; select one report explicitly"
        raise ReportError(message)
    scan, prefix = matches[0]
    if len({check.name for check in scan.checks}) != len(scan.checks):
        message = "Duplicate Scorecard check names are ambiguous"
        raise ReportError(message)
    issues = [
        Issue(
            origin="OSSF",
            check=check.name,
            score=check.score,
            status="unavailable" if check.score == -1 else "gap",
            evidence=check.model_dump_json(),
            location=f"{prefix}/checks/{index}",
        )
        for index, check in enumerate(scan.checks)
        if check.score < MAX_SCORE
    ]
    return Report(
        repository=repository,
        source=source.model_copy(
            update={
                "version": scan.scorecard.version,
                "audited_commit": scan.repo.commit,
                "scan_date": scan.date,
            }
        ),
        issues=issues,
        notices=[
            (
                "Scores below the maximum are candidate findings, not failures; "
                "unavailable evidence is not a defect."
            )
        ],
    )
