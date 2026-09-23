# noqa: CPY001
"""Inspect, propose and explicitly publish selected repository remedies."""

from pathlib import Path
from typing import Annotated

import os

import httpx
import typer
from pydantic_core import PydanticSerializationError

from RepoRemedy import __version__
from RepoRemedy.batch import run_batch
from RepoRemedy.context.github import ContextError
from RepoRemedy.interactive import run_inspection, run_plan_publication
from RepoRemedy.propose import ProposalBundle, RouteChoice
from RepoRemedy.publication.publish import publish_remedies
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
    """Inspect audits, propose remedies individually or in batches, and publish selections."""
    # Keep offline inspection, proposal review and confirmed publication separate.


@app.command()
def inspect(
    report: Annotated[Path | None, typer.Argument(exists=True, dir_okay=False, readable=True)] = None,
    report_type: Annotated[ReportType | None, typer.Option("--report-type")] = None,
    repo: Annotated[
        str | None, typer.Option("--repo", help="OWNER/REPO or a GitHub.com/Enterprise HTTPS repository URL.")
    ] = None,
    interactive: Annotated[  # noqa: FBT002 - Typer flag
        bool, typer.Option("--interactive", help="Select and review remedies in a TUI.")
    ] = False,
    plan: Annotated[Path, typer.Option("--plan", help="New saved session path.")] = Path("remedy-plan.json"),
    resume: Annotated[Path | None, typer.Option("--resume", exists=True, dir_okay=False)] = None,
    token_env: Annotated[str | None, typer.Option("--token-env")] = None,
) -> None:
    """Inspect offline findings as JSON, or continue interactively through remedy review."""
    try:
        if resume is not None:
            if report is not None or report_type is not None or repo is not None:
                message = "--resume cannot be combined with a report, --report-type or --repo"
                raise typer.BadParameter(message)
            run_inspection(None, resume, resume=True, token_env=token_env)
            return
        if report is None or report_type is None or repo is None:
            message = "Provide REPORT, --report-type and --repo, or use --resume"
            raise typer.BadParameter(message)
        result = read_report(report, report_type, repo)
        if interactive:
            run_inspection(result, plan, token_env=token_env)
        else:
            typer.echo(result.model_dump_json(indent=2))
    except (ReportError, ContextError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    except (PydanticSerializationError, OSError, ValueError) as exc:
        typer.echo(
            "Error: Cannot serialize or write report output; check session files if resuming", err=True
        )
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


@app.command()
def publish(
    bundle: Annotated[Path | None, typer.Argument(exists=True, dir_okay=False, readable=True)] = None,
    repo: Annotated[
        str | None, typer.Option("--repo", help="Confirm the target GitHub.com/Enterprise repository.")
    ] = None,
    select: Annotated[
        list[str] | None, typer.Option("--select", help="Remedy ID to publish; repeat for each selection.")
    ] = None,
    receipts: Annotated[
        Path | None, typer.Option("--receipts", help="Persistent publication receipt JSON file.")
    ] = None,
    confirm: Annotated[  # noqa: FBT002 - Typer boolean option
        bool, typer.Option("--confirm", help="Confirm publication of exactly these selections.")
    ] = False,
    token_env: Annotated[str, typer.Option("--token-env")] = "REPOREMEDY_TOKEN",  # noqa: S107
    plan: Annotated[Path | None, typer.Option("--plan", exists=True, dir_okay=False)] = None,
) -> None:
    """Publish selected remedies as issues or draft PRs and persist receipts."""
    try:
        if plan is not None:
            if (
                any(value is not None for value in (bundle, repo, select, receipts))
                or token_env != "REPOREMEDY_TOKEN"  # noqa: S105 - variable name
            ):
                message = "--plan uses its saved repository, selections, receipts and token variable"
                raise typer.BadParameter(message)
            result = run_plan_publication(plan, confirmed=confirm)
            if result is not None:
                typer.echo(result.model_dump_json(indent=2))
            return
        if bundle is None or repo is None or not select or receipts is None:
            message = "Provide BUNDLE, --repo, --select and --receipts, or use --plan"
            raise typer.BadParameter(message)
        if not confirm:
            typer.echo("Error: Review the selected proposals, then pass --confirm to publish", err=True)
            raise typer.Exit(2)
        if bundle.resolve() == receipts.resolve():
            typer.echo("Error: Receipts must not overwrite the proposal bundle", err=True)
            raise typer.Exit(2)
        if bundle.stat().st_size > 32 * 1024 * 1024:
            typer.echo("Error: Proposal bundle exceeds the supported size limit", err=True)
            raise typer.Exit(2)
        saved = ProposalBundle.model_validate_json(bundle.read_bytes())
        with httpx.Client(trust_env=False) as client:
            result = publish_remedies(
                saved,
                select,
                repo,
                receipts,
                client,
                token=os.environ.get(token_env, ""),
                confirmed=confirm,
            )
        typer.echo(result.model_dump_json(indent=2))
    except (ContextError, ReportError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    except (OSError, ValueError, PydanticSerializationError) as exc:
        typer.echo(
            "Error: Cannot validate publication or persist receipts; inspect the receipt file before retrying",
            err=True,
        )
        raise typer.Exit(2) from exc
