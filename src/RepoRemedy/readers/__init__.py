# noqa: CPY001
"""Explicit report selection and source provenance."""

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from pydantic import ValidationError

from RepoRemedy.models import Report, ReportType, Source
from RepoRemedy.readers.common import ReportError, fail, repository_name
from RepoRemedy.readers.repoauditor import read_repoauditor
from RepoRemedy.readers.scorecard import read_scorecard

MAX_BYTES = 10 * 1024 * 1024


def read_report(path: Path, report_type: ReportType | str, repository: str) -> Report:
    """Read a bounded UTF-8 report; errors never include the report contents."""
    repository = repository_name(repository)
    reader = {ReportType.REPOAUDITOR: read_repoauditor, ReportType.SCORECARD: read_scorecard}.get(report_type)
    if reader is None:
        fail("Unsupported report type; choose repoauditor or ossf-scorecard")
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            fail("Report exceeds the 10 MiB limit")
        source = Source(
            path=str(path.resolve()),
            sha256=hashlib.sha256(raw).hexdigest(),
            report_type=ReportType(report_type),
        )
        return reader(raw.decode("utf-8-sig"), repository, source)
    except ReportError:
        raise
    except ValidationError as exc:
        fail(
            "Unsupported or malformed report fields: "
            + ", ".join(".".join(map(str, error["loc"])) for error in exc.errors(include_input=False))
        )
    except OSError, ValueError, RecursionError:
        fail("Cannot read report: require an accessible UTF-8 file in the selected format")
