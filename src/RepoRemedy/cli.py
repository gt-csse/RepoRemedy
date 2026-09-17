# noqa: CPY001
"""Installable report-inspection command."""

from pathlib import Path  # noqa: TC003 - Typer resolves annotations at runtime
from typing import Annotated

import typer
from pydantic_core import PydanticSerializationError

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
    _show_version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True)] = False,  # noqa: FBT002
) -> None:
    """Inspect repository audit reports and prepare for reviewable remediation."""
    # Retain subcommands so offline inspection and future publication remain separate actions.


@app.command()
def inspect(
    report: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    report_type: Annotated[ReportType, typer.Option("--report-type")],
    repo: Annotated[
        str, typer.Option("--repo", help="OWNER/REPO or a GitHub.com/Enterprise HTTPS repository URL.")
    ],
) -> None:
    """Write normalized issues and source provenance as JSON to stdout."""
    try:
        result = read_report(report, report_type, repo)
        typer.echo(result.model_dump_json(indent=2))
    except ReportError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    except (PydanticSerializationError, OSError) as exc:
        typer.echo("Error: Cannot serialize or write report output", err=True)
        raise typer.Exit(2) from exc
