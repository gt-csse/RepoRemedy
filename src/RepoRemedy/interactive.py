# noqa: CPY001
"""CLI adapters for interactive inspection and single-repository saved plans."""

from typing import TYPE_CHECKING
import os
import sys

import httpx

from RepoRemedy.context.github import ContextError
from RepoRemedy.plan import RemedyPlan, load_plan
from RepoRemedy.publication.publish import publish_remedies

if TYPE_CHECKING:
    from pathlib import Path
    from RepoRemedy.models import Report
    from RepoRemedy.publication.receipts import ReceiptJournal


def run_inspection(
    report: Report | None,
    path: Path,
    *,
    resume: bool = False,
    token_env: str | None = None,
) -> None:
    """Require a terminal and avoid replacing another session accidentally."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        message = "Interactive inspection requires a terminal; omit --interactive for JSON output"
        raise ContextError(message)
    if resume:
        plan = load_plan(path)
    else:
        if path.exists():
            message = "Plan already exists; use --resume or choose a new --plan path"
            raise ContextError(message)
        assert report is not None
        plan = RemedyPlan(report=report)
    if token_env is not None:
        plan = RemedyPlan.model_validate(plan.model_dump() | {"token_env": token_env})
    from RepoRemedy.tui import RemedyApp  # noqa: PLC0415 - keep Textual out of JSON commands

    RemedyApp(plan, path.resolve(), resumed=resume).run()


def run_plan_publication(path: Path, *, confirmed: bool = False) -> ReceiptJournal | None:
    """Open confirmation in a terminal, or publish reviewed selections with --confirm."""
    plan = load_plan(path)
    bundle = plan.validate_publication()
    if not confirmed:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            message = "Plan publication requires a terminal confirmation or --confirm"
            raise ContextError(message)
        from RepoRemedy.tui import RemedyApp  # noqa: PLC0415 - keep Textual out of JSON commands

        RemedyApp(plan, path.resolve(), publish_only=True).run()
        return None
    with httpx.Client(trust_env=False) as client:
        return publish_remedies(
            bundle,
            plan.selected,
            plan.report.repository,
            plan.get_receipt_path(path),
            client,
            token=os.environ.get(plan.token_env, ""),
            confirmed=True,
        )
