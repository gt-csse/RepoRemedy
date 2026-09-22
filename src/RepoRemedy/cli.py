# noqa: CPY001
"""Inspect reports and prepare concrete remedies for separate publication."""

from pathlib import Path  # noqa: TC003 - Typer resolves annotations at runtime
from typing import Annotated

import os

import httpx
import typer
from pydantic_core import PydanticSerializationError

from RepoRemedy import __version__
from RepoRemedy.batch import run_batch
from RepoRemedy.context.github import ContextError
from RepoRemedy.propose import RouteChoice  # noqa: TC001 - Typer resolves annotations at runtime
from RepoRemedy.models import ReportType  # noqa: TC001 - Typer resolves annotations at runtime
from RepoRemedy.readers import read_report
from RepoRemedy.readers.common import ReportError
from RepoRemedy.workflow import propose_repository

app = typer.Typer(name="RepoRemedy", no_args_is_help=True, pretty_exceptions_enable=False)


def _version(value: bool) -> None:  # noqa: FBT001
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    _show_version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True)] = False,  # noqa: FBT002
) -> None:
    """Inspect audits and propose remedies for one repository or a batch."""
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


@app.command()
def propose(
    report: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    report_type: Annotated[ReportType, typer.Option("--report-type")],
    repo: Annotated[str, typer.Option("--repo", help="OWNER/REPO or a GitHub Enterprise repository URL.")],
    ref: Annotated[
        str | None,
        typer.Option("--ref", help="Branch or full SHA; defaults to the audit commit, otherwise main."),
    ] = None,
    inputs: Annotated[
        Path | None, typer.Option("--inputs", exists=True, dir_okay=False, readable=True)
    ] = None,
    route: Annotated[
        RouteChoice, typer.Option(help="Prefer an eligible PR, or request only issues/PRs.")
    ] = "auto",
    approve_inputs: Annotated[
        list[str] | None,
        typer.Option("--approve-inputs", help="Remedy ID whose content inputs you approve; repeatable."),
    ] = None,
    token_env: Annotated[
        str, typer.Option("--token-env", help="Environment variable containing a token for this host.")
    ] = "REPOREMEDY_TOKEN",  # noqa: S107 - environment variable name, not a token
) -> None:
    """Gather context and write rendered issue/draft PR proposals as JSON; never publish."""
    try:
        with httpx.Client(trust_env=False) as client:
            result = propose_repository(
                report,
                report_type,
                repo,
                client,
                ref=ref,
                inputs=inputs,
                route=route,
                approved_inputs=set(approve_inputs or []),
                token=os.environ.get(token_env),
            )
        typer.echo(result.model_dump_json(indent=2))
    except (ContextError, ReportError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    except (OSError, ValueError, PydanticSerializationError, RecursionError) as exc:
        typer.echo("Error: Cannot collect context, validate inputs or write proposals", err=True)
        raise typer.Exit(2) from exc


@app.command("propose-batch")
def propose_batch(
    manifest: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output: Annotated[Path, typer.Option("--output", help="New directory for bundles and summaries.")],
) -> None:
    """Save proposal bundles and summaries for a repository manifest without publishing.

    Exit 0 on success, 3 on partial failure, and 2 if nothing succeeds or a global
    configuration/output error occurs. Relative input templates use the manifest's
    directory; --output is a new directory relative to the current working directory.
    """
    try:
        with httpx.Client(trust_env=False) as client:
            summary = run_batch(manifest, output, client)
        typer.echo(summary.model_dump_json(indent=2))
    except (OSError, ValueError, PydanticSerializationError) as exc:
        typer.echo(
            "Error: Cannot read batch configuration or write results; inspect configuration and saved summaries",
            err=True,
        )
        raise typer.Exit(2) from exc
    raise typer.Exit(summary.exit_code or 0)
