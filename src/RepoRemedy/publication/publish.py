# noqa: CPY001
"""Publish only selected, confirmed and freshly validated catalog remedies."""

from dataclasses import dataclass
import datetime
import hashlib
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, JsonValue

from RepoRemedy.catalog import load_catalog
from RepoRemedy.context import collect_context
from RepoRemedy.context.github import encode_segment
from RepoRemedy.context.repository_context import GitSha
from RepoRemedy.propose import Proposal, ProposalBundle, propose_remedies
from RepoRemedy.publication.github import GitHubPublisher, PublishedTarget
from RepoRemedy.publication.receipts import (
    PublicationError,
    PublicationReceipt,
    ReceiptJournal,
    ReceiptStore,
    load_receipts,
)
from RepoRemedy.readers.common import repository_name

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import httpx

    from RepoRemedy.context import RepositoryContext


def get_publication_key(repository: str, remedy_id: str) -> str:
    """Identify a remedy across reports, routes, content revisions and retries."""
    return hashlib.sha256(f"{repository}\0{remedy_id}".encode()).hexdigest()


def _rebuild_proposal(bundle: ProposalBundle, proposal: Proposal, context: RepositoryContext) -> Proposal:
    """Re-run catalog guards and rendering, preserving explicit inputs and approvals."""
    supplied = {
        name: value.value
        for name, value in proposal.inputs.items()
        if value.source == "user input; approval not established"
    }
    report = bundle.report.model_copy(update={"issues": proposal.findings})
    result = propose_remedies(
        report,
        context,
        {proposal.remedy_id: supplied} if proposal.remedy_id else {},
        approved_inputs=set(bundle.approved_inputs),
        route="auto" if proposal.route == "issue" and proposal.guards else proposal.route,
    )
    if len(result.proposals) != 1:
        message = "A selected remedy must identify exactly one reviewed finding"
        raise PublicationError(message)
    return result.proposals[0]


def select_proposals(bundle: ProposalBundle, selected: list[str], repository: str) -> list[Proposal]:
    """Validate the saved bundle and explicit selection before any remote writes.

    Saved readiness is not trusted by itself: the selected proposals are rebuilt
    with the installed catalog and recorded context, including file-creation guards.
    Edited content or stale catalog versions require a new reviewed proposal.
    """
    if not selected or len(set(selected)) != len(selected):
        message = "Select one or more distinct remedy IDs explicitly"
        raise PublicationError(message)
    if (
        repository_name(repository) != bundle.repository
        or bundle.repository != bundle.context.repository
        or bundle.repository != bundle.report.repository
        or bundle.base_commit != bundle.context.commit_sha
        or bundle.report_sha256 != bundle.report.source.sha256
        or bundle.context_sha256 != hashlib.sha256(bundle.context.model_dump_json().encode()).hexdigest()
        or bundle.catalog_sha256 != load_catalog().sha256
    ):
        message = "Bundle provenance or target differs; regenerate and review proposals"
        raise PublicationError(message)
    proposals = []
    for identifier in selected:
        matches = [p for p in bundle.proposals if p.remedy_id == identifier]
        if len(matches) != 1 or matches[0].status != "ready" or matches[0].content is None:
            message = f"Selected remedy {identifier} must uniquely identify a ready proposal"
            raise PublicationError(message)
        proposal = matches[0]
        if not proposal.findings or any(finding not in bundle.report.issues for finding in proposal.findings):
            message = "Selected findings do not match the reviewed report"
            raise PublicationError(message)
        rebuilt = _rebuild_proposal(bundle, proposal, bundle.context)
        if rebuilt != proposal:
            message = "Selected remedy differs from validated catalog output; regenerate and review it"
            raise PublicationError(message)
        proposals.append(proposal)
    return proposals


def _check_branch(publisher: GitHubPublisher, bundle: ProposalBundle) -> None:
    branch = publisher.read_object(f"/branches/{encode_segment(bundle.context.settings_branch)}")
    commit = branch.get("commit")
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if TypeAdapter(GitSha).validate_python(sha) != bundle.base_commit:
        message = "Target branch has moved since review; regenerate proposals"
        raise PublicationError(message)


def _check_freshness(
    publisher: GitHubPublisher, bundle: ProposalBundle, proposal: Proposal, token: str
) -> None:
    """Require the reviewed branch head and selected evidence to remain unchanged.

    A fresh context re-evaluates current settings, inheritance and file guards.
    Any branch advance is conservatively stale, even if unrelated files changed.
    This is a preflight check, not a transaction locking GitHub against other users.
    """
    metadata = publisher.read_object()
    permissions = metadata.get("permissions")
    if (
        metadata.get("archived")
        or metadata.get("disabled")
        or (
            proposal.route == "pr"
            and (not isinstance(permissions, dict) or permissions.get("push") is not True)
        )
        or (proposal.route == "issue" and metadata.get("has_issues") is False)
    ):
        message = "Repository does not permit the selected publication route"
        raise PublicationError(message)
    _check_branch(publisher, bundle)
    context = collect_context(
        bundle.repository,
        publisher.client,
        ref=bundle.context.settings_branch,
        token=token,
    )
    rebuilt = _rebuild_proposal(bundle, proposal, context)
    if context.commit_sha != bundle.base_commit or rebuilt != proposal:
        message = "Repository evidence or remedy readiness changed; regenerate and review proposals"
        raise PublicationError(message)


def _check_publication_branch(publisher: GitHubPublisher, branch: str, commit_sha: str | None) -> bool:
    """Require branch absence or the exact recorded commit, without creating refs."""
    existing = publisher.read(f"/git/ref/heads/{encode_segment(branch)}")
    if existing.status == "available":
        value = existing.value
        obj = value.get("object") if isinstance(value, dict) else None
        if not commit_sha or not isinstance(obj, dict) or obj.get("sha") != commit_sha:
            message = "Publication branch exists with unrecorded or changed content; reconcile it manually"
            raise PublicationError(message)
        return True
    if existing.reason != "GitHub HTTP 404":
        message = "Cannot establish publication branch absence"
        raise PublicationError(message)
    return False


def _check_previous_receipt(
    previous: PublicationReceipt | None, bundle: ProposalBundle, proposal: Proposal, digest: str
) -> None:
    """Use the same reconciliation rule in preflight and publication."""
    if previous and (
        previous.status != "pending"
        or previous.content_sha256 != digest
        or previous.base_commit != bundle.base_commit
        or previous.route != proposal.route
    ):
        message = "Prior publication cannot be reconciled; inspect receipts and GitHub before retrying"
        raise PublicationError(message)


def _prepare_branch(
    publisher: GitHubPublisher,
    bundle: ProposalBundle,
    proposal: Proposal,
    receipt: PublicationReceipt,
    store: ReceiptStore,
) -> None:
    """Create a dedicated branch without updating existing refs or the base branch.

    Save the commit identity before creating its ref. A retry can reuse that exact
    ref, but cannot replace an unrelated branch or publish a branch changed by others.
    """
    assert proposal.content is not None
    assert receipt.branch is not None
    if _check_publication_branch(publisher, receipt.branch, receipt.commit_sha):
        return
    if receipt.commit_sha is None:
        entries: list[JsonValue] = [
            {"path": file.path.as_posix(), "mode": "100644", "type": "blob", "content": file.content}
            for file in proposal.content.files
        ]
        tree = publisher.post("/git/trees", {"base_tree": bundle.context.tree_sha, "tree": entries})
        tree_sha = TypeAdapter(GitSha).validate_python(tree.get("sha"))
        commit = publisher.post(
            "/git/commits",
            {
                "message": proposal.content.title,
                "tree": tree_sha,
                "parents": [bundle.base_commit],
            },
        )
        receipt.commit_sha = TypeAdapter(GitSha).validate_python(commit.get("sha"))
        store.save()
    publisher.post("/git/refs", {"ref": f"refs/heads/{receipt.branch}", "sha": receipt.commit_sha})


def _record_target(receipt: PublicationReceipt, target: PublishedTarget, store: ReceiptStore) -> None:
    receipt.route = target.route
    receipt.number = target.number
    receipt.url = target.url
    receipt.updated_at = datetime.datetime.now(datetime.UTC)
    store.save()


def _publish_one(
    publisher: GitHubPublisher,
    bundle: ProposalBundle,
    proposal: Proposal,
    store: ReceiptStore,
    token: str,
) -> None:
    assert proposal.remedy_id is not None
    assert proposal.content is not None
    identifier = proposal.remedy_id
    key = get_publication_key(bundle.repository, identifier)
    marker = f"<!-- reporemedy:v1:{key} -->"
    digest = hashlib.sha256(proposal.content.model_dump_json().encode()).hexdigest()
    previous = store.journal.receipts.get(identifier)
    duplicate = publisher.find_duplicate(proposal, marker)
    if duplicate:
        receipt = PublicationReceipt(
            base_commit=bundle.base_commit,
            remedy_id=identifier,
            route=proposal.route,
            content_sha256=digest,
            status="existing",
            updated_at=datetime.datetime.now(datetime.UTC),
        )
        store.journal.receipts[identifier] = receipt
        _record_target(receipt, duplicate, store)
        return
    _check_previous_receipt(previous, bundle, proposal, digest)
    _check_freshness(publisher, bundle, proposal, token)
    receipt = previous or PublicationReceipt(
        base_commit=bundle.base_commit,
        remedy_id=identifier,
        route=proposal.route,
        content_sha256=digest,
        updated_at=datetime.datetime.now(datetime.UTC),
        branch=f"reporemedy/{key}" if proposal.route == "pr" else None,
    )
    store.journal.receipts[identifier] = receipt
    store.save()
    if proposal.route == "pr":
        _prepare_branch(publisher, bundle, proposal, receipt, store)
    # Recheck after preparatory writes and just before issuing the visible creation.
    _check_branch(publisher, bundle)
    duplicate = publisher.find_duplicate(proposal, marker)
    if duplicate:
        receipt.status = "existing"
        _record_target(receipt, duplicate, store)
        return
    if proposal.route == "pr":
        branch = publisher.read_object(f"/git/ref/heads/{encode_segment(receipt.branch or '')}")
        obj = branch.get("object")
        if not isinstance(obj, dict) or obj.get("sha") != receipt.commit_sha:
            message = "Publication branch changed before PR creation; reconcile it manually"
            raise PublicationError(message)
    receipt.status = "uncertain"
    store.save()
    payload: dict[str, JsonValue] = {
        "title": proposal.content.title,
        "body": proposal.content.body + "\n\n" + marker,
    }
    if proposal.route == "pr":
        payload.update(head=receipt.branch, base=bundle.context.settings_branch, draft=True)
    response = publisher.post("/pulls" if proposal.route == "pr" else "/issues", payload)
    target = publisher.identify_target(response, proposal.route)
    receipt.status = "created"
    _record_target(receipt, target, store)


@dataclass(frozen=True)
class PreflightItem:
    """One checked selection: an existing target, a possible creation or a blocker."""

    remedy_id: str
    existing: PublishedTarget | None = None
    error: str | None = None


@dataclass(frozen=True)
class PublicationPreflight:
    """Read-only observations, not authorization or a lock on remote state.

    Existing matches follow publisher reuse rules: they need no creation access
    or fresh branch. New objects pass the existing route, evidence, branch and
    receipt checks. GitHub can still reject a write; publication rechecks state.
    """

    items: list[PreflightItem]
    checked_at: datetime.datetime

    def can_publish(self) -> bool:
        """Enable confirmation only after every selection has passed its checks."""
        return bool(self.items) and all(item.error is None for item in self.items)


def preflight_remedies(
    bundle: ProposalBundle,
    selected: list[str],
    repository: str,
    receipt_path: Path,
    client: httpx.Client,
    *,
    token: str,
) -> PublicationPreflight:
    """Check expected creations and reuse with GETs only; leave all files untouched.

    Fail closed for unreadable journals or active publishers. A snapshot may become
    stale immediately; publish_remedies always repeats validation under its lock.
    Errors from remote response bodies and credentials are never displayed.
    """
    if not token.strip():
        message = "Set the configured token environment variable before checking publication"
        raise PublicationError(message)
    proposals = select_proposals(bundle, selected, repository)
    if receipt_path.with_name(receipt_path.name + ".lock").exists():
        message = "Receipt journal is locked; wait for the active publisher before checking again"
        raise PublicationError(message)
    journal = load_receipts(receipt_path, bundle.repository)
    publisher = GitHubPublisher(bundle.repository, client, token)
    items = []
    for proposal in proposals:
        assert proposal.remedy_id is not None
        assert proposal.content is not None
        identifier = proposal.remedy_id
        key = get_publication_key(bundle.repository, identifier)
        try:
            duplicate = publisher.find_duplicate(proposal, f"<!-- reporemedy:v1:{key} -->")
            if not duplicate:
                previous = journal.receipts.get(identifier)
                digest = hashlib.sha256(proposal.content.model_dump_json().encode()).hexdigest()
                _check_previous_receipt(previous, bundle, proposal, digest)
                _check_freshness(publisher, bundle, proposal, token)
                if proposal.route == "pr":
                    _check_publication_branch(
                        publisher,
                        previous.branch if previous and previous.branch else f"reporemedy/{key}",
                        previous.commit_sha if previous else None,
                    )
        except PublicationError as exc:
            items.append(PreflightItem(identifier, error=str(exc)))
        except ValueError:
            items.append(PreflightItem(identifier, error="Cannot validate repository evidence; check again"))
        else:
            items.append(PreflightItem(identifier, existing=duplicate))
    return PublicationPreflight(items, datetime.datetime.now(datetime.UTC))


def publish_remedies(
    bundle: ProposalBundle,
    selected: list[str],
    repository: str,
    receipt_path: Path,
    client: httpx.Client,
    *,
    token: str,
    confirmed: bool = False,
    on_published: Callable[[PublicationReceipt], None] | None = None,
) -> ReceiptJournal:
    """Publish explicit selections after confirmation, retaining partial progress.

    This single operation has explicit dependencies and no global mutable state.
    Stateful clients and receipt storage are classes. The receipt lock spans the
    run; each completed item survives a later item's failure. Uncertain final POSTs
    are never retried blindly. Only selected content is sent, never the bundle.
    on_published receives a copy after each completed receipt is durably saved.
    Preflight results never replace this operation's checks or confirmation.
    """
    if confirmed is not True or not token.strip():
        message = "Publication requires explicit confirmation and a token for the target host"
        raise PublicationError(message)
    proposals = select_proposals(bundle, selected, repository)
    publisher = GitHubPublisher(bundle.repository, client, token)
    with ReceiptStore(receipt_path, bundle.repository) as store:
        for proposal in proposals:
            _publish_one(publisher, bundle, proposal, store, token)
            if on_published is not None:
                assert proposal.remedy_id is not None
                on_published(store.journal.receipts[proposal.remedy_id].model_copy(deep=True))
        return store.journal
