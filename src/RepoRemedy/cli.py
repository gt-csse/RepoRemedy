# noqa: CPY001
"""Installable report-inspection command."""

from pathlib import Path  # noqa: TC003 - Typer resolves annotations at runtime
from typing import Annotated

import typer

from RepoRemedy import __version__
from RepoRemedy.models import ReportType  # noqa: TC001 - Typer resolves annotations at runtime
from RepoRemedy.readers import read_report
from RepoRemedy.readers.common import ReportError

app = typer.Typer(name="RepoRemedy", no_args_is_help=True, pretty_exceptions_enable=False)


def _version(value: bool) -> None:  # noqa: FBT001
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True)] = False,  # noqa: FBT002
) -> None:
    """Inspect repository audit reports without modifying repositories."""


@app.command()
def inspect(
    report: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    report_type: Annotated[ReportType, typer.Option("--report-type")],
    repo: Annotated[str, typer.Option("--repo", help="OWNER/REPO or GitHub repository URL.")],
) -> None:
    """Write normalized issues and source provenance as JSON to stdout."""
    try:
        result = read_report(report, report_type, repo)
    except ReportError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(result.model_dump_json(indent=2))
