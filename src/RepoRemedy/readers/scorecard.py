# noqa: CPY001
"""Read Scorecard v5 JSON, including audit-tool envelopes and scan arrays."""

import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from RepoRemedy.models import Issue, Report, Source
from RepoRemedy.readers.common import fail, repository_name

MAX_SCORE = 10
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
    version: Annotated[str, Field(pattern=r"^v5\.\d+\.\d+(?:[-+].+)?$")]


class _Scan(BaseModel):
    model_config = ConfigDict(strict=True)
    repo: _Repository
    scorecard: _Version
    checks: Annotated[list[_Check], Field(min_length=1)]
    date: str | None = None


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len(dict(pairs)) != len(pairs):
        fail("Duplicate JSON object keys are ambiguous")
    return dict(pairs)


def read_scorecard(text: str, repository: str, source: Source) -> Report:
    """Validate all supplied scans and require exactly one repository match."""
    data = json.loads(text, object_pairs_hook=_object, parse_constant=fail)
    candidates = data if isinstance(data, list) else [data]
    matches = []
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            fail("Scorecard scans must be JSON objects")
        wrapped = "meta" in item
        scan = _Scan.model_validate(item.get("scorecard") if wrapped else item)
        prefix = (f"/{index}" if isinstance(data, list) else "") + ("/scorecard" if wrapped else "")
        if repository_name(scan.repo.name) == repository:
            matches.append((scan, prefix))
    if len(matches) != 1:
        fail("Expected exactly one scan matching the repository; select one report explicitly")
    scan, prefix = matches[0]
    if len({check.name for check in scan.checks}) != len(scan.checks):
        fail("Duplicate Scorecard check names are ambiguous")
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
