"""Shared report and repository fixtures for remedy service tests."""

from pathlib import Path

from RepoRemedy.models import Issue, Report, ReportType, Source
from repository_context_test import FakeGitHub


def make_report(check="SecurityPolicy", *, origin="RA", status="warning", commit=None):
    return Report(
        repository="acme/demo",
        source=Source(
            path=Path("audit.txt"), sha256="e" * 64, report_type=ReportType.REPOAUDITOR, audited_commit=commit
        ),
        issues=[
            Issue(
                origin=origin, check=check, status=status, evidence="Example evidence", location="lines:1-3"
            )
        ],
        notices=[],
    )


def make_snapshot():
    api = FakeGitHub()
    api.file(
        "README.md",
        "# Demo\n\n## Installation\nuv sync\n\n## Usage\nRun demo\n\n## Support\nAsk maintainers\n",
    )
    api.file(
        "CONTRIBUTING.md",
        "# Contributing\n\n## Development setup\nuv sync\n\n## Testing\nuv run pytest\n\n## Submitting changes\nOpen a PR\n",
    )
    api.file(
        "docs/SECURITY.md",
        "# Security\n\n## Reporting a vulnerability\nUse the private reporting form\n\n## Supported versions\n1.x\n",
    )
    api.file(".github/workflows/test.yml", "name: CI")
    api.file("pyproject.toml", "[project]\nname='demo'\n")
    return api.snapshot()
