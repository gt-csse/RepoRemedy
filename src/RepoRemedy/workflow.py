# noqa: CPY001
"""Shared single-repository proposal workflow for CLI and batch callers."""

import json
import os
from typing import TYPE_CHECKING

from pydantic import TypeAdapter

from RepoRemedy.context import collect_context
from RepoRemedy.context.github import ContextError
from RepoRemedy.propose import ProposalBundle, RouteChoice, propose_remedies
from RepoRemedy.readers import read_report

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

    from RepoRemedy.models import ReportType


def propose_repository(
    report: Path,
    report_type: ReportType,
    repository: str,
    client: httpx.Client,
    *,
    ref: str | None = None,
    inputs: Path | None = None,
    route: RouteChoice = "auto",
    approved_inputs: set[str] | None = None,
    token: str | None = None,
) -> ProposalBundle:
    """Read, collect and render identically for one report in either workflow.

    The audit's commit is preferred when no ref is supplied, falling back to main.
    Missing inputs, unsupported findings and guard failures remain proposal states,
    not execution failures. Neither this operation nor its batch caller publishes.

    report and inputs are caller-resolved paths. Input files must be JSON objects
    mapping remedy IDs to string-valued fields, at most 1 MiB. Parsing and shape
    validation precede context collection; catalog rules are enforced during rendering.
    Input approvals are explicit remedy IDs and do not authorize publication.

    Return the same self-contained ProposalBundle used by the single CLI command.
    No artifacts are written here, and the caller retains ownership of client.
    Report/context, validation, and filesystem errors propagate so each caller can
    decide whether to stop or record the failure and continue.
    """
    normalized = read_report(report, report_type, repository)
    supplied = {}
    if inputs is not None:
        limit = 1024 * 1024
        with inputs.open("rb") as stream:
            if os.fstat(stream.fileno()).st_size > limit:
                message = "Inputs exceed the supported size limit"
                raise ContextError(message)
            # Retain the bound and post-read check for files that grow after fstat.
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            message = "Inputs exceed the supported size limit"
            raise ContextError(message)
        supplied = TypeAdapter(dict[str, dict[str, str]]).validate_python(json.loads(raw), strict=True)
    snapshot = collect_context(
        normalized.repository,
        client,
        ref=ref if ref is not None else normalized.source.audited_commit or "main",
        token=token,
    )
    return propose_remedies(normalized, snapshot, supplied, approved_inputs=approved_inputs, route=route)
