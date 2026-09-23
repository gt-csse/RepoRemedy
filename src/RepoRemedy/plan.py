# noqa: CPY001
"""Resumable single-repository selections, inputs and exact-content review.

The plan embeds the existing proposal bundle so moving it does not lose evidence.
Receipt paths are relative to the plan. Credentials are never stored. Editing a
plan is not a validation bypass: publication still rebuilds selected proposals.
"""

from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Literal
import hashlib
import os
import tempfile

from pydantic import BaseModel, ConfigDict, Field, model_validator

from RepoRemedy.catalog import load_catalog
from RepoRemedy.context import collect_context
from RepoRemedy.context.github import ContextError
from RepoRemedy.context.resolve import PROTECTED_INPUTS
from RepoRemedy.models import Report  # noqa: TC001 - Pydantic runtime field
from RepoRemedy.propose import Proposal, ProposalBundle, RouteChoice, propose_remedies
from RepoRemedy.publication.publish import select_proposals

if TYPE_CHECKING:
    import httpx

MAX_PLAN_BYTES = 32 * 1024 * 1024


def get_review_digest(bundle: ProposalBundle, proposal: Proposal) -> str:
    """Bind review to the proposal, repository, evidence, catalog and base commit."""
    content = (
        f"{bundle.repository}\n{bundle.base_commit}\n{bundle.report_sha256}\n"
        f"{bundle.context_sha256}\n{bundle.catalog_sha256}\n{proposal.model_dump_json()}"
    )
    return hashlib.sha256(content.encode()).hexdigest()


class RemedyPlan(BaseModel):
    """Local session; selection, input approval and content review are distinct."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    report: Report
    bundle: ProposalBundle | None = None
    selected: list[str] = Field(default_factory=list)
    reviewed: dict[str, str] = Field(default_factory=dict)
    inputs: dict[str, dict[str, str]] = Field(default_factory=dict)
    routes: dict[str, RouteChoice] = Field(default_factory=dict)
    token_env: str = Field(default="REPOREMEDY_TOKEN", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    receipts: Path = Path("publication-receipts.json")

    @model_validator(mode="after")
    def validate_session(self) -> RemedyPlan:
        """Reject contradictory saved identities and duplicate selections."""
        if len(self.selected) != len(set(self.selected)) or set(self.reviewed) - set(self.selected):
            message = "Plan selections or review identities are inconsistent"
            raise ValueError(message)
        if self.bundle is not None and self.bundle.report != self.report:
            message = "Plan report differs from its proposal bundle"
            raise ValueError(message)
        if set(self.selected) - self.get_selectable_ids():
            message = "Plan selects unsupported, unavailable or ambiguous remedies"
            raise ValueError(message)
        return self

    def get_proposals(self) -> list[Proposal]:
        """Return the existing proposal records, including blocked findings."""
        return self.bundle.proposals if self.bundle else []

    def get_selectable_ids(self) -> set[str]:
        """Keep unavailable, unsupported and ambiguous remedy identities visible only."""
        counts = Counter(p.remedy_id for p in self.get_proposals())
        return {
            p.remedy_id
            for p in self.get_proposals()
            if p.remedy_id and counts[p.remedy_id] == 1 and p.status not in {"unavailable", "unsupported"}
        }

    def get_proposal(self, identifier: str) -> Proposal:
        """Resolve one unambiguous proposal without discarding duplicate evidence."""
        matches = [p for p in self.get_proposals() if p.remedy_id == identifier]
        if len(matches) != 1:
            message = "Remedy must identify exactly one proposal"
            raise ContextError(message)
        return matches[0]

    def set_selected(self, identifier: str, *, selected: bool) -> None:
        """Change selection independently of input approval and publication."""
        if identifier not in self.get_selectable_ids():
            message = "Remedy is unsupported, unavailable or ambiguous"
            raise ContextError(message)
        if selected and identifier not in self.selected:
            self.selected.append(identifier)
        elif not selected and identifier in self.selected:
            self.selected.remove(identifier)
            self.reviewed.pop(identifier, None)

    def collect(self, client: httpx.Client) -> None:
        """Collect context once, then reuse the catalog engine for local previews."""
        context = collect_context(
            self.report.repository,
            client,
            ref=self.report.source.audited_commit or "main",
            token=os.environ.get(self.token_env),
        )
        bundle = propose_remedies(self.report, context, self.inputs)
        catalog = load_catalog().remedies
        for proposal in bundle.proposals:
            identifier = proposal.remedy_id
            if identifier and identifier not in self.routes:
                self.routes[identifier] = "pr" if catalog[identifier].pr else "issue"
        self.bundle = bundle
        self.regenerate()

    def regenerate(self) -> None:
        """Render from cached context and invalidate reviews whose content changed."""
        assert self.bundle is not None
        previous = self.bundle
        bundle = propose_remedies(
            self.report,
            previous.context,
            self.inputs,
            approved_inputs=set(previous.approved_inputs),
        )
        for index, proposal in enumerate(bundle.proposals):
            identifier = proposal.remedy_id
            if identifier in self.routes:
                report = self.report.model_copy(update={"issues": proposal.findings})
                rendered = propose_remedies(
                    report,
                    bundle.context,
                    self.inputs,
                    approved_inputs=set(bundle.approved_inputs),
                    route=self.routes[identifier],
                )
                bundle.proposals[index] = rendered.proposals[0]
        self.bundle = bundle
        selectable = self.get_selectable_ids()
        self.selected = [identifier for identifier in self.selected if identifier in selectable]
        self.reviewed = {
            identifier: digest
            for identifier, digest in self.reviewed.items()
            if identifier in self.selected and self.is_reviewed(identifier)
        }

    def get_editable_inputs(self, identifier: str, route: RouteChoice) -> dict[str, str]:
        """Return catalog fields with their current resolved or supplied values."""
        proposal = self.get_proposal(identifier)
        remedy = load_catalog().remedies[identifier]
        definition = remedy.pr if route == "pr" else remedy.issue
        if definition is None:
            message = "This remedy does not support a draft PR"
            raise ContextError(message)
        return {
            key: self.inputs.get(identifier, {}).get(
                key,
                proposal.inputs[key].value if key in proposal.inputs else "",
            )
            for key in definition.required_inputs
            if key not in PROTECTED_INPUTS
        }

    def update_inputs(self, identifier: str, route: RouteChoice, values: dict[str, str]) -> None:
        """Approve input values, regenerate locally and require a new content review."""
        assert self.bundle is not None
        allowed = self.get_editable_inputs(identifier, route)
        if set(values) - allowed.keys() or any(not value.strip() for value in values.values()):
            message = "Fill the required fields with nonempty values"
            raise ContextError(message)
        candidate = self.model_copy(deep=True)
        assert candidate.bundle is not None
        candidate.inputs[identifier] = values
        candidate.routes[identifier] = route
        if identifier not in candidate.bundle.approved_inputs:
            candidate.bundle.approved_inputs.append(identifier)
        candidate.reviewed.pop(identifier, None)
        candidate.regenerate()
        self.inputs, self.routes = candidate.inputs, candidate.routes
        self.bundle, self.reviewed = candidate.bundle, candidate.reviewed

    def is_reviewed(self, identifier: str) -> bool:
        """Check review against the current proposal rather than a saved boolean."""
        return bool(
            self.bundle
            and self.reviewed.get(identifier) == get_review_digest(self.bundle, self.get_proposal(identifier))
        )

    def approve(self, identifier: str) -> None:
        """Record exact-content review only after the existing publisher validates it."""
        if self.bundle is None or identifier not in self.selected:
            message = "Select a remedy before approving its proposal"
            raise ContextError(message)
        proposal = select_proposals(self.bundle, [identifier], self.report.repository)[0]
        self.reviewed[identifier] = get_review_digest(self.bundle, proposal)

    def validate_publication(self) -> ProposalBundle:
        """Require every selection to be ready and reviewed before any remote writes."""
        if (
            self.bundle is None
            or not self.selected
            or any(not self.is_reviewed(identifier) for identifier in self.selected)
        ):
            message = "Review every selected proposal before publication"
            raise ContextError(message)
        select_proposals(self.bundle, self.selected, self.report.repository)
        return self.bundle

    def get_receipt_path(self, plan_path: Path) -> Path:
        """Resolve receipt paths beside the plan and protect its source artifacts."""
        result = (plan_path.parent / self.receipts).resolve()
        if result in {plan_path.resolve(), self.report.source.path.resolve()}:
            message = "Receipts must not overwrite the plan or source report"
            raise ContextError(message)
        return result


def load_plan(path: Path) -> RemedyPlan:
    """Read a bounded UTF-8 plan, checking size before allocation and after growth."""
    with path.open("rb") as stream:
        if os.fstat(stream.fileno()).st_size > MAX_PLAN_BYTES:
            message = "Plan exceeds the supported size limit"
            raise ContextError(message)
        raw = stream.read(MAX_PLAN_BYTES + 1)
    if len(raw) > MAX_PLAN_BYTES:
        message = "Plan exceeds the supported size limit"
        raise ContextError(message)
    plan = RemedyPlan.model_validate_json(raw)
    plan.get_receipt_path(path)
    return plan


def save_plan(plan: RemedyPlan, path: Path) -> None:
    """Atomically save a private session without modifying reports or receipts."""
    if path.resolve() in {plan.report.source.path.resolve(), plan.get_receipt_path(path)}:
        message = "Plan must not overwrite its source report or receipts"
        raise ContextError(message)
    raw = plan.model_dump_json(indent=2).encode()
    if len(raw) > MAX_PLAN_BYTES:
        message = "Plan exceeds the supported size limit"
        raise ContextError(message)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
