# noqa: CPY001
"""Thin Textual interface over the report, plan and publication services."""

from typing import TYPE_CHECKING, ClassVar
import os
import webbrowser

import httpx
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Checkbox,
    ContentSwitcher,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    ProgressBar,
    Select,
    SelectionList,
    TextArea,
)
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

from RepoRemedy.context.github import ContextError
from RepoRemedy.plan import RemedyPlan, save_plan
from RepoRemedy.publication.publish import publish_remedies
from RepoRemedy.publication.receipts import PublicationReceipt, ReceiptJournal  # noqa: TC001 - Textual callbacks
from RepoRemedy.review import ReviewScreen, render_proposal

if TYPE_CHECKING:
    from pathlib import Path


class RemedyApp(App[None]):
    """Keep UI state local; run context collection and publication off the UI thread."""

    TITLE = "RepoRemedy"
    CSS = """
    Screen { background: $surface; }
    #pages { height: 1fr; }
    #repository, #summary, #publication-summary, #notice { height: auto; padding: 1; }
    .buttons { height: auto; min-height: 3; }
    .buttons Button { margin: 0 1 0 0; min-width: 10; }
    #filters { height: 3; }
    #search { width: 2fr; }
    #filter { width: 1fr; }
    #candidates { width: 1fr; }
    #details { width: 1fr; }
    #selection-body { height: 1fr; }
    #dialog { width: 95%; height: 95%; background: $surface; border: solid $primary; padding: 1; }
    ModalScreen { align: center middle; }
    #preview { height: 1fr; min-height: 8; }
    #fields { height: 1fr; min-height: 6; }
    .input-field { height: 5; }
    #findings, #evidence, #results { height: 1fr; }
    #confirmation { height: auto; }
    """
    BINDINGS: ClassVar = [("ctrl+s", "save", "Save"), ("ctrl+q", "quit", "Save / exit")]

    def __init__(self, plan: RemedyPlan, path: Path, *, publish_only: bool = False) -> None:
        super().__init__()
        self.plan = plan
        self.path = path
        self.publish_only = publish_only
        self.busy = False
        self.visible_indices: list[int] = []
        self.results: list[PublicationReceipt] = []

    def compose(self) -> ComposeResult:
        """Use library controls for selection, previews, forms, progress and results."""
        yield Header()
        yield Label(self.plan.report.repository, id="repository", markup=False)
        with ContentSwitcher(
            initial="publication" if self.publish_only else "selection" if self.plan.bundle else "inspection",
            id="pages",
        ):
            with Vertical(id="inspection"):
                yield Label("Audit findings (offline). Continue to collect repository context.")
                yield OptionList(
                    *[
                        Option(Text(f"{finding.origin} / {finding.check}: {finding.status}"))
                        for finding in self.plan.report.issues
                    ],
                    id="findings",
                )
                yield TextArea(read_only=True, id="evidence")
                yield Button("Select remedies", id="continue", variant="primary")
            with Vertical(id="selection"):
                yield Label(id="summary", markup=False)
                with Horizontal(id="filters"):
                    yield Input(placeholder="Search remedies or evidence", id="search")
                    yield Select(
                        [(s, s) for s in ["All", "Ready", "Needs input", "Selected"]],
                        value="All",
                        allow_blank=False,
                        id="filter",
                    )
                with Horizontal(id="selection-body"):
                    yield SelectionList[int](id="candidates")
                    yield TextArea(read_only=True, id="details")
                with Horizontal(classes="buttons"):
                    yield Button("Select filtered", id="select-filtered")
                    yield Button("Clear filtered", id="clear-filtered")
                    yield Button("Review", id="review", variant="primary")
                    yield Button("Publish", id="prepare-publication")
                    yield Button("Save / exit", id="save-exit")
            with Vertical(id="publication"):
                yield Label(id="publication-summary", markup=False)
                yield Checkbox("Publish exactly these selections to the repository above", id="confirmation")
                with Horizontal(classes="buttons"):
                    yield Button("Publish selected", id="publish", variant="primary")
                    yield Button("Back to selections", id="back-to-selection")
                yield ProgressBar(total=len(self.plan.selected), show_eta=False, id="progress")
                yield OptionList(id="results")
                yield Button("Open selected result", id="open-result", disabled=True)
        yield Label(id="notice", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        """Restore a saved plan without implicitly publishing it."""
        if self.plan.bundle:
            self.show_candidates()
        if self.publish_only:
            self.prepare_publication()

    def show_notice(self, message: str) -> None:
        """Display plain text without interpreting report or exception markup."""
        self.query_one("#notice", Label).update(message)

    @on(OptionList.OptionHighlighted, "#findings")
    def show_evidence(self, event: OptionList.OptionHighlighted) -> None:
        """Keep original report evidence readable before any GitHub access."""
        finding = self.plan.report.issues[event.option_index]
        self.query_one("#evidence", TextArea).load_text(f"{finding.location}\n\n{finding.evidence}")

    @on(Button.Pressed, "#continue")
    def continue_inspection(self) -> None:
        """Start context collection only when the user continues inspection."""
        self.busy = True
        self.query_one("#continue", Button).disabled = True
        self.show_notice("Collecting repository context...")
        self.collect_context()

    @work(thread=True)
    def collect_context(self) -> None:
        """Keep network work out of the terminal event loop."""
        try:
            with httpx.Client(trust_env=False) as client:
                self.plan.collect(client)
        except ContextError, OSError, ValueError:
            self.call_from_thread(self.finish_collection, succeeded=False)
        else:
            self.call_from_thread(self.finish_collection, succeeded=True)

    def finish_collection(self, succeeded: bool) -> None:  # noqa: FBT001 - worker result
        """Restore input after collection, retaining offline findings on failure."""
        self.busy = False
        self.query_one("#continue", Button).disabled = False
        if succeeded:
            self.query_one("#pages", ContentSwitcher).current = "selection"
            self.show_candidates()
            self.show_notice("Select remedies, complete inputs, then review. Nothing has been published.")
        else:
            self.show_notice(
                "Cannot collect context. Check repository access and the configured token variable."
            )

    @on(Input.Changed, "#search")
    @on(Select.Changed, "#filter")
    def show_candidates(self) -> None:
        """Filter views without losing selections outside the current view."""
        query = self.query_one("#search", Input).value.casefold()
        status = self.query_one("#filter", Select).value
        candidates = self.query_one("#candidates", SelectionList)
        highlighted = (
            candidates.get_option_at_index(candidates.highlighted).value
            if candidates.highlighted is not None
            else None
        )
        selectable = self.plan.get_selectable_ids()
        self.visible_indices = []
        options = []
        for index, proposal in enumerate(self.plan.get_proposals()):
            identifier = proposal.remedy_id
            name = identifier or proposal.findings[0].check
            searchable = " ".join([name, *(f.evidence for f in proposal.findings)]).casefold()
            if query not in searchable or (
                (status == "Ready" and proposal.status != "ready")
                or (status == "Needs input" and proposal.status != "needs-input")
                or (status == "Selected" and identifier not in self.plan.selected)
            ):
                continue
            self.visible_indices.append(index)
            label = f"{name}  / {proposal.route} / {proposal.status}"
            if identifier not in selectable:
                label += " (not selectable; unsupported, unavailable or duplicate)"
            options.append(
                Selection(
                    Text(label),
                    index,
                    identifier in self.plan.selected,
                    disabled=identifier not in selectable,
                )
            )
        candidates.clear_options().add_options(options)
        candidates.highlighted = (
            self.visible_indices.index(highlighted)
            if highlighted in self.visible_indices
            else 0
            if options
            else None
        )
        reviewed = sum(self.plan.is_reviewed(identifier) for identifier in self.plan.selected)
        self.query_one("#summary", Label).update(
            f"{len(self.plan.selected)} / {len(self.plan.get_proposals())} selected; "
            f"{reviewed} reviewed. Mode: templates."
        )

    @on(SelectionList.SelectionToggled, "#candidates")
    def toggle_candidate(self, event: SelectionList.SelectionToggled[int]) -> None:
        """Track explicit user toggles, not list rebuild notifications."""
        proposal = self.plan.get_proposals()[event.selection.value]
        assert proposal.remedy_id is not None
        self.plan.set_selected(
            proposal.remedy_id, selected=event.selection.value in event.selection_list.selected
        )
        self.show_candidates()

    @on(SelectionList.SelectionHighlighted, "#candidates")
    def show_details(self, event: SelectionList.SelectionHighlighted[int]) -> None:
        """Show reasons and evidence even when the finding cannot be selected."""
        proposal = self.plan.get_proposals()[event.selection.value]
        if proposal.remedy_id in self.plan.get_selectable_ids():
            assert proposal.remedy_id is not None
            detail = render_proposal(self.plan, proposal.remedy_id)
        else:
            detail = "\n".join([*(f.evidence for f in proposal.findings), *proposal.reasons])
        self.query_one("#details", TextArea).load_text(detail)

    @on(Button.Pressed, "#select-filtered")
    @on(Button.Pressed, "#clear-filtered")
    def select_filtered(self, event: Button.Pressed) -> None:
        """Apply bulk actions only to the currently visible eligible remedies."""
        selectable = self.plan.get_selectable_ids()
        for index in self.visible_indices:
            identifier = self.plan.get_proposals()[index].remedy_id
            if identifier in selectable:
                assert identifier is not None
                self.plan.set_selected(identifier, selected=event.button.id == "select-filtered")
        self.show_candidates()

    @on(Button.Pressed, "#review")
    def review_selected(self) -> None:
        """Review the saved order of explicit selections."""
        if self.plan.selected:
            self.push_screen(ReviewScreen(self.plan), lambda _: self.show_candidates())
        else:
            self.show_notice("Select at least one remedy to review.")

    def persist(self) -> bool:
        """Keep the session open if saving fails instead of losing the user's work."""
        try:
            save_plan(self.plan, self.path)
        except OSError, ValueError, ContextError:
            self.show_notice("Cannot save plan. Check its path, permissions and size; session remains open.")
            return False
        self.show_notice(f"Saved {self.path}")
        return True

    def action_save(self) -> None:
        """Save selections and reviews without remote writes."""
        if not self.busy:
            self.persist()

    @on(Button.Pressed, "#save-exit")
    async def action_quit(self) -> None:
        """Do not exit during a remote operation or discard an unsaved session."""
        if self.busy:
            self.show_notice("Wait for the current operation; completed publications are saved in receipts.")
        elif self.persist():
            self.exit()

    @on(Button.Pressed, "#prepare-publication")
    def prepare_publication(self) -> None:
        """Require all selected content to pass review before confirmation."""
        try:
            self.plan.validate_publication()
        except ContextError, ValueError:
            self.show_notice(
                "Every selection must be ready and reviewed. Complete inputs or deselect blocked items."
            )
            self.query_one("#pages", ContentSwitcher).current = "selection"
            return
        if not self.persist():
            return
        self.query_one("#pages", ContentSwitcher).current = "publication"
        prs = sum(self.plan.get_proposal(i).route == "pr" for i in self.plan.selected)
        self.query_one("#publication-summary", Label).update(
            f"Publish {len(self.plan.selected)} selections: {prs} draft PRs, "
            f"{len(self.plan.selected) - prs} issues. Existing matches will be reused.\n"
            "Repository state and permissions are rechecked before each new publication."
        )
        self.query_one("#confirmation", Checkbox).value = False

    @on(Button.Pressed, "#back-to-selection")
    def return_to_selection(self) -> None:
        """Allow edits before publication or after a completed attempt."""
        if not self.busy:
            self.query_one("#pages", ContentSwitcher).current = "selection"
            self.show_candidates()

    @on(Button.Pressed, "#publish")
    def start_publication(self) -> None:
        """Require explicit confirmation for each publication attempt."""
        if not self.query_one("#confirmation", Checkbox).value:
            self.show_notice("Check the confirmation box to publish these selections.")
            return
        if self.busy:
            return
        self.results = []
        self.query_one("#results", OptionList).clear_options()
        self.query_one("#progress", ProgressBar).update(total=len(self.plan.selected), progress=0)
        self.busy = True
        self.query_one("#publish", Button).disabled = True
        self.query_one("#back-to-selection", Button).disabled = True
        self.query_one("#confirmation", Checkbox).disabled = True
        self.show_notice("Publishing. Completed results are saved before the next remedy starts.")
        self.publish_selected()

    @work(thread=True)
    def publish_selected(self) -> None:
        """Delegate writes and retry semantics to the unchanged publication engine."""
        try:
            bundle = self.plan.validate_publication()
            with httpx.Client(trust_env=False) as client:
                journal = publish_remedies(
                    bundle,
                    self.plan.selected,
                    self.plan.report.repository,
                    self.plan.get_receipt_path(self.path),
                    client,
                    token=os.environ.get(self.plan.token_env, ""),
                    confirmed=True,
                    on_published=lambda receipt: self.call_from_thread(self.record_result, receipt),
                )
        except ContextError, OSError, ValueError:
            self.call_from_thread(self.finish_publication, None)
        else:
            self.call_from_thread(self.finish_publication, journal)

    def record_result(self, receipt: PublicationReceipt) -> None:
        """Display only durable completed results and their actual returned links."""
        self.results.append(receipt)
        self.query_one("#results", OptionList).add_option(
            Option(Text(f"{receipt.remedy_id}: {receipt.status} ({receipt.route}) {receipt.url}"))
        )
        if self.query_one("#results", OptionList).highlighted is None:
            self.query_one("#results", OptionList).highlighted = 0
        self.query_one("#progress", ProgressBar).update(progress=len(self.results))
        self.query_one("#open-result", Button).disabled = False

    def finish_publication(self, journal: ReceiptJournal | None) -> None:
        """Preserve completed results when a later remedy needs reconciliation."""
        self.busy = False
        self.query_one("#publish", Button).disabled = False
        self.query_one("#back-to-selection", Button).disabled = False
        self.query_one("#confirmation", Checkbox).disabled = False
        self.query_one("#confirmation", Checkbox).value = False
        created = sum(r.status == "created" for r in self.results)
        self.show_notice(
            f"{created} created, {len(self.results) - created} reused. "
            + (
                "Complete. Draft PRs await maintainer review."
                if journal
                else "Stopped. Inspect receipts before retrying; unfinished selections remain saved."
            )
        )

    @on(Button.Pressed, "#open-result")
    @on(OptionList.OptionSelected, "#results")
    def open_result(self) -> None:
        """Open a verified publisher URL only after an explicit user action."""
        index = self.query_one("#results", OptionList).highlighted
        if index is not None and self.results[index].url:
            url = self.results[index].url
            assert url is not None
            webbrowser.open(url)
