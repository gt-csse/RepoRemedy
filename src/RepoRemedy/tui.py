# noqa: CPY001
"""Thin Textual interface over the report, plan and publication services."""

from typing import TYPE_CHECKING, ClassVar
import os
import webbrowser

import httpx
from rich.text import Text
from textual.binding import Binding
from textual.theme import Theme
from textual.message import Message
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Checkbox,
    ContentSwitcher,
    Footer,
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
from RepoRemedy.publication.publish import (
    PublicationPreflight,
    preflight_remedies,
    publish_remedies,
)
from RepoRemedy.publication.receipts import (
    PublicationReceipt,
    ReceiptJournal,
    load_receipts,
)
from RepoRemedy.review import InputScreen, ReviewScreen, get_remedy_name

if TYPE_CHECKING:
    from pathlib import Path


class RemedySelection(SelectionList[int]):
    """Notify the app when library layout changes require reflowing column labels."""

    BINDINGS: ClassVar = [Binding("space", "select", "Toggle")]

    class Resized(Message):
        """The selection viewport has a new terminal size."""

    def on_resize(self) -> None:
        """Let the app reformat labels after Textual has completed layout."""
        self.post_message(self.Resized())


class RemedyApp(App[None]):
    """Keep UI state local; run context collection and publication off the UI thread."""

    TITLE = "RepoRemedy"
    CSS_PATH = "tui.tcss"
    BINDINGS: ClassVar = [
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+q", "quit", "Save / exit"),
        Binding("slash", "search", "Search", key_display="/"),
        Binding("f", "filter", "Filter"),
        Binding("a", "select_filtered", "Select filtered"),
        Binding("enter", "continue", "Review / continue", priority=True),
        Binding("escape", "selection", "Back"),
    ]

    def __init__(
        self, plan: RemedyPlan, path: Path, *, publish_only: bool = False, resumed: bool = False
    ) -> None:
        super().__init__()
        self.HORIZONTAL_BREAKPOINTS = [(0, "compact"), (100, "wide")]
        self.register_theme(
            Theme(
                name="reporemedy",
                primary="#72D5E5",
                secondary="#A6B5C3",
                accent="#72D5E5",
                foreground="#E6EDF3",
                background="#101820",
                surface="#101820",
                panel="#202D38",
                success="#9DDEAE",
                warning="#F1C778",
                error="#F08C8C",
            )
        )
        self.theme = "reporemedy"
        self.plan = plan
        self.path = path
        self.publish_only = publish_only
        self.resumed = resumed
        self.busy = False
        self.visible_indices: list[int] = []
        self.results: list[PublicationReceipt] = []
        self.preflight: PublicationPreflight | None = None
        self.checked_plan: str | None = None

    def compose(self) -> ComposeResult:
        """Arrange library controls in the mockup's full-width terminal layout."""
        yield Label("RepoRemedy  /  INSPECT · SELECT · REVIEW · PUBLISH", id="app-title")
        yield Label(
            f"Repository  {self.plan.report.repository}    Mode: Templates", id="repository", markup=False
        )
        with ContentSwitcher(initial="inspection", id="pages"):
            with Vertical(id="inspection"):
                yield Label("REPORT LOADED", classes="heading")
                yield Label(
                    f"Source  {self.plan.report.source.path.name}\n"
                    f"Findings  {len(self.plan.report.issues)}  ·  Browse evidence before continuing",
                    classes="muted",
                    markup=False,
                )
                yield OptionList(
                    *[Option(Text(f"{f.check:<28} {f.evidence}")) for f in self.plan.report.issues],
                    id="findings",
                )
                yield TextArea(read_only=True, id="evidence", show_cursor=False)
                yield Button("Continue to remedy selection", id="continue", variant="primary")
            with Vertical(id="selection"):
                yield Label("SELECT REMEDIES", classes="heading")
                yield Label(id="summary", markup=False)
                with Horizontal(id="filters"):
                    yield Input(placeholder="Search remedies or evidence  (/)", id="search")
                    yield Select(
                        [(s, s) for s in ["All", "Ready", "Needs input", "Selected"]],
                        value="All",
                        allow_blank=False,
                        id="filter",
                    )
                yield Label(id="column-headings", classes="muted", markup=False)
                yield RemedySelection(id="candidates")
                yield Label(id="visible-count", classes="muted", markup=False)
                yield TextArea(read_only=True, id="details", show_cursor=False)
                with Horizontal(classes="buttons"):
                    yield Button("Select filtered", id="select-filtered")
                    yield Button("Clear filtered", id="clear-filtered")
                    yield Button("Review", id="review", variant="primary")
                    yield Button("Publish", id="prepare-publication")
                    yield Button("Save / exit", id="save-exit")
            yield from self.compose_session_pages()
            with Vertical(id="publication"):
                yield Label("PUBLICATION CHECK", id="publication-title", classes="heading")
                yield Label(id="publication-summary", markup=False)
                with Vertical(id="publication-checks"):
                    yield Label(id="preflight-status", markup=False, classes="muted")
                    yield TextArea(read_only=True, id="preflight-details", show_cursor=False)
                    yield Checkbox(
                        "Publish exactly these selections to this repository",
                        id="confirmation",
                        disabled=True,
                    )
                    yield Button("Publish selected", id="publish", variant="primary", disabled=True)
                with Vertical(id="publication-results"):
                    yield ProgressBar(total=len(self.plan.selected), show_eta=False, id="progress")
                    yield Label(id="result-counts", markup=False)
                    yield Label(f"{'REMEDY':<34}{'RESULT':<18}ACTION", classes="muted")
                    yield OptionList(id="results")
                    yield Label(id="result-link", markup=False, classes="muted")
                    yield Button("Open selected result", id="open-result", disabled=True)
                with Horizontal(classes="buttons"):
                    yield Button("Check again / retry", id="check-again")
                    yield Button("Back to selections", id="back-to-selection")
                    yield Button("Save / exit", id="publication-exit")
        yield Label("No publication has been authorized.", id="notice", markup=False)
        yield Footer(show_command_palette=False)

    def compose_session_pages(self) -> ComposeResult:
        """Keep save and restore summaries together, separate from selection controls."""
        with Vertical(id="review-complete"):
            yield Label("REVIEW COMPLETE", classes="heading success")
            yield Label(id="review-summary", markup=False, classes="session-summary")
            yield Label("No issues or PRs have been published by this review.", classes="muted")
            with Horizontal(classes="buttons"):
                yield Button("Save and exit", id="finish-save", variant="primary")
                yield Button("Continue to publication", id="finish-publish")
                yield Button("Change selections", id="finish-back")
        with Vertical(id="resume"):
            yield Label("SAVED SESSION RESTORED", classes="heading")
            yield Label(id="resume-summary", markup=False, classes="session-summary")
            yield Label("Changing content requires a new review of the affected proposals.", classes="muted")
            yield OptionList(
                "Continue with the saved publication plan",
                "Review selected proposals",
                "Change selections or inputs",
                "Save and exit",
                id="resume-options",
            )

    def on_mount(self) -> None:
        """Restore local state; only an explicit publication view performs preflight."""
        self.watch(self.query_one("#candidates"), "scroll_y", self.show_visible_count, init=False)
        self.query_one("#publication-results").display = False
        self.show_target()
        self.query_one("#findings", OptionList).highlighted = 0 if self.plan.report.issues else None
        if self.plan.bundle:
            self.show_page("selection")
            self.call_after_refresh(self.show_candidates)
        if self.resumed:
            self.query_one("#resume-summary", Label).update(self.get_session_summary())
            self.show_page("resume")
        if self.publish_only:
            self.prepare_publication()

    def show_target(self) -> None:
        """Name the resolved publication branch and reviewed commit before consent."""
        bundle = self.plan.bundle
        target = (
            f"Branch {bundle.context.settings_branch} @ {bundle.base_commit[:12]}"
            if bundle
            else f"Ref {self.plan.ref or self.plan.report.source.audited_commit or 'repository default branch'}"
        )
        self.query_one("#repository", Label).update(f"{self.plan.report.repository}  ·  {target}")

    def show_page(self, page: str) -> None:
        """Move between workflow states and focus the primary keyboard control."""
        self.show_target()
        self.query_one("#pages", ContentSwitcher).current = page
        primary = {
            "inspection": "#findings",
            "selection": "#candidates",
            "resume": "#resume-options",
            "review-complete": "#finish-save",
            "publication": "#back-to-selection",
        }
        self.query_one(primary[page]).focus()
        self.refresh_bindings()

    def get_session_summary(self) -> str:
        """Show counts derived from actual selections, never illustrative mockup data."""
        proposals = [self.plan.get_proposal(i) for i in self.plan.selected]
        reviewed = sum(self.plan.is_reviewed(i) for i in self.plan.selected)
        ready = sum(p.status == "ready" for p in proposals)
        prs = sum(p.route == "pr" for p in proposals)
        return (
            f"Selected         {len(proposals)} / {len(self.plan.get_proposals())}\n"
            f"Reviewed         {reviewed} / {len(proposals)}\n"
            f"Ready            {ready}\nNeeds attention  {len(proposals) - ready}\n"
            f"Draft PRs        {prs}\nIssues           {len(proposals) - prs}\n\nPlan  {self.path}"
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:  # noqa: ARG002 - Textual signature
        """Keep single-letter shortcuts out of forms and limit them to their step."""
        if action in {"save", "quit"}:
            return True
        if len(self.screen_stack) > 1 or self.busy:
            return False
        if action == "selection" and isinstance(self.focused, Input):
            return True
        if isinstance(self.focused, Input | TextArea | Select):
            return False
        page = self.query_one("#pages", ContentSwitcher).current
        if action in {"search", "filter", "select_filtered"}:
            return page == "selection"
        if action == "continue":
            return bool(self.focused and self.focused.id in {"findings", "candidates"})
        if action == "selection":
            return page in {"resume", "review-complete", "publication"}
        return True

    def action_search(self) -> None:
        """Focus the library search input."""
        self.query_one("#search", Input).focus()

    def action_filter(self) -> None:
        """Focus the library filter menu."""
        self.query_one("#filter", Select).focus()

    def action_select_filtered(self) -> None:
        """Select eligible rows without changing hidden selections."""
        self.set_filtered(selected=True)

    def action_continue(self) -> None:
        """Continue inspection or review selected remedies with Enter."""
        if self.query_one("#pages", ContentSwitcher).current == "inspection":
            self.continue_inspection()
        else:
            self.review_selected()

    def action_selection(self) -> None:
        """Return to selections without changing approvals."""
        if isinstance(self.focused, Input):
            self.query_one("#candidates").focus()
        else:
            self.return_to_selection()

    @on(OptionList.OptionSelected, "#resume-options")
    def resume_session(self, event: OptionList.OptionSelected) -> None:
        """Offer publication, review, editing or save/exit after restoration."""
        match event.option_index:
            case 0:
                self.prepare_publication()
            case 1:
                self.return_to_selection()
                self.review_selected()
            case 2:
                self.return_to_selection()
            case 3:
                self.call_later(self.action_quit)

    @on(TextArea.Changed)
    def refresh_text(self, event: TextArea.Changed) -> None:
        """Repaint changed text even when Textual's wrapped document size is unchanged."""
        event.text_area.refresh()

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
        if self.busy:
            return
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
            self.show_page("selection")
            self.call_after_refresh(self.show_candidates)
            self.show_notice("Select remedies, complete inputs, then review. Nothing has been published.")
        else:
            self.show_notice(
                "Cannot collect context. Check repository access and the configured token variable."
            )

    @on(Input.Changed, "#search")
    @on(Select.Changed, "#filter")
    def show_candidates(self) -> None:
        """Filter views without losing selections outside the current view."""
        if not self.is_running:
            return
        if not self.query("#candidates"):
            return
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
        name_width = max(16, candidates.size.width - 33)
        self.query_one("#column-headings", Label).update(f"{'REMEDY':<{name_width}}  {'ACTION':<10} STATUS")
        for index, proposal in enumerate(self.plan.get_proposals()):
            identifier = proposal.remedy_id
            name = get_remedy_name(identifier) if identifier else proposal.findings[0].check
            searchable = " ".join(
                [name, identifier or "", *(f.evidence for f in proposal.findings)]
            ).casefold()
            if query not in searchable or (
                (status == "Ready" and proposal.status != "ready")
                or (status == "Needs input" and proposal.status != "needs-input")
                or (status == "Selected" and identifier not in self.plan.selected)
            ):
                continue
            self.visible_indices.append(index)
            label = Text(name, style="dim" if identifier not in selectable else "")
            label.truncate(name_width, overflow="ellipsis", pad=True)
            route = "Draft PR" if proposal.route == "pr" else "Issue"
            status_text = proposal.status.replace("-", " ").capitalize()
            if identifier not in selectable:
                status_text = "Not selectable"
            color = "#9DDEAE" if proposal.status == "ready" else "#F1C778"
            label.append(f"  {route:<10} ")
            label.append(status_text, style=color if identifier in selectable else "dim")
            options.append(
                Selection(
                    label, index, identifier in self.plan.selected, disabled=identifier not in selectable
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
        proposals = self.plan.get_proposals()
        eligible = [p for p in proposals if p.remedy_id in selectable]
        ready = sum(p.status == "ready" for p in eligible)
        needs_input = sum(p.status == "needs-input" for p in eligible)
        needs_review = len(eligible) - ready - needs_input
        unavailable = len(proposals) - len(eligible)
        reviewed = sum(self.plan.is_reviewed(i) for i in self.plan.selected)
        self.query_one("#summary", Label).update(
            f"{len(self.plan.selected)} / {len(proposals)} selected    ·    {reviewed} reviewed\n"
            f"{ready} ready  ·  {needs_input} need input  ·  {needs_review} need review  ·  {unavailable} not selectable"
        )
        review_button = self.query_one("#review", Button)
        review_button.label = f"Review {len(self.plan.selected)}"
        review_button.refresh()
        self.show_visible_count()
        if candidates.highlighted is not None:
            self.show_candidate_details(candidates.get_option_at_index(candidates.highlighted).value)
        else:
            self.query_one("#details", TextArea).load_text("No matching remedies. Change search or filter.")

    @on(RemedySelection.Resized)
    def resize_candidates(self) -> None:
        """Fit columns to the actual viewport after Textual applies its breakpoints."""
        if self.is_running and self.query("#candidates"):
            self.call_after_refresh(self.show_candidates)

    def show_visible_count(self) -> None:
        """Describe the visible row range within the filtered list."""
        if not self.is_running:
            return
        candidates = self.query_one("#candidates", SelectionList)
        count = len(self.visible_indices)
        start = min(count, int(candidates.scroll_y) + 1)
        end = min(count, int(candidates.scroll_y) + candidates.scrollable_content_region.height)
        self.query_one("#visible-count", Label).update(f"Showing {start}-{end} of {count} matching remedies")

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
        self.call_after_refresh(self.show_visible_count)
        self.show_candidate_details(event.selection.value)

    def show_candidate_details(self, index: int) -> None:
        """Refresh evidence even when a rebuilt list retains the same highlighted row."""
        if not self.is_running:
            return
        proposal = self.plan.get_proposals()[index]
        detail = "\n".join(
            [
                *(f"Evidence: {f.check} ({f.location}): {f.evidence}" for f in proposal.findings),
                *proposal.reasons,
            ]
        )
        self.query_one("#details", TextArea).load_text(detail)

    @on(Button.Pressed, "#select-filtered")
    @on(Button.Pressed, "#clear-filtered")
    def select_filtered(self, event: Button.Pressed) -> None:
        """Apply bulk actions only to the currently visible eligible remedies."""
        self.set_filtered(selected=event.button.id == "select-filtered")

    def set_filtered(self, *, selected: bool) -> None:
        """Apply a bulk selection to visible eligible IDs only."""
        selectable = self.plan.get_selectable_ids()
        for index in self.visible_indices:
            identifier = self.plan.get_proposals()[index].remedy_id
            if identifier in selectable:
                assert identifier is not None
                self.plan.set_selected(identifier, selected=selected)
        self.show_candidates()

    @on(Button.Pressed, "#review")
    def review_selected(self) -> None:
        """Review the saved order of explicit selections."""
        if self.plan.selected:
            self.push_screen(ReviewScreen(self.plan), self.finish_review)
        else:
            self.show_notice("Select at least one remedy to review.")

    def finish_review(self, _result: None = None) -> None:
        """Show a dedicated summary only when every selected proposal is reviewed."""
        self.show_candidates()
        if self.plan.selected and all(self.plan.is_reviewed(i) for i in self.plan.selected):
            self.query_one("#review-summary", Label).update(self.get_session_summary())
            self.show_page("review-complete")
            self.show_notice("Review complete. Save the plan or continue to publication checks.")

    def persist(self) -> bool:
        """Keep the session open if saving fails instead of losing the user's work."""
        try:
            if isinstance(self.screen, InputScreen):
                self.screen.save_draft()
            save_plan(self.plan, self.path)
        except OSError, ValueError, ContextError:
            self.show_notice("Cannot save plan. Check its path, permissions and size; session remains open.")
            self.notify(
                "Cannot save plan; session remains open. Check path, permissions and size.", severity="error"
            )
            return False
        self.show_notice(f"Saved {self.path}")
        if len(self.screen_stack) > 1:
            self.notify("Session saved. Input drafts remain unapproved.")
        return True

    def action_save(self) -> None:
        """Save selections and reviews without remote writes."""
        if not self.busy:
            self.persist()

    @on(Button.Pressed, "#save-exit")
    @on(Button.Pressed, "#finish-save")
    @on(Button.Pressed, "#publication-exit")
    async def action_quit(self) -> None:
        """Do not exit during a remote operation or discard an unsaved session."""
        if self.busy:
            self.show_notice("Wait for the current operation; completed publications are saved in receipts.")
        elif self.persist():
            self.exit()

    @on(Button.Pressed, "#prepare-publication")
    @on(Button.Pressed, "#finish-publish")
    @on(Button.Pressed, "#check-again")
    def prepare_publication(self) -> None:
        """Validate review, save the plan and perform read-only checks before consent."""
        if self.busy:
            return
        try:
            self.plan.validate_publication()
        except ContextError, ValueError:
            self.show_notice(
                "Every selection must be ready and reviewed. Complete inputs or deselect blocked items."
            )
            self.return_to_selection()
            return
        if not self.persist():
            return
        self.preflight = None
        self.checked_plan = None
        self.show_page("publication")
        self.query_one("#publication-title", Label).update("PUBLICATION CHECK")
        prs = sum(self.plan.get_proposal(i).route == "pr" for i in self.plan.selected)
        self.query_one("#publication-summary", Label).update(
            f"Selected  {len(self.plan.selected)} reviewed remedies    ·    {prs} draft PRs / {len(self.plan.selected) - prs} issues"
        )
        self.query_one("#publication-checks").display = True
        self.query_one("#publication-results").display = False
        self.query_one("#confirmation", Checkbox).value = False
        self.query_one("#confirmation", Checkbox).disabled = True
        self.query_one("#publish", Button).disabled = True
        self.query_one("#preflight-status", Label).update(
            "[ok] Saved proposals and approvals match.\nChecking repository evidence, routes, receipts and existing matches..."
        )
        self.query_one("#preflight-details", TextArea).load_text("")
        self.set_publication_busy(busy=True)
        self.show_notice("Read-only checks. No issues, PRs, branches or receipts are created.")
        self.check_publication()

    def set_publication_busy(self, *, busy: bool) -> None:
        """Prevent edits, retries and exit controls during network operations."""
        self.busy = busy
        for identifier in ("check-again", "back-to-selection", "publication-exit"):
            self.query_one(f"#{identifier}", Button).disabled = busy
        self.refresh_bindings()

    @work(thread=True)
    def check_publication(self) -> None:
        """Run preflight off the event loop without authorizing any writes."""
        try:
            bundle = self.plan.validate_publication()
            with httpx.Client(trust_env=False) as client:
                result = preflight_remedies(
                    bundle,
                    self.plan.selected,
                    self.plan.report.repository,
                    self.plan.get_receipt_path(self.path),
                    client,
                    token=os.environ.get(self.plan.token_env, ""),
                )
        except ContextError, OSError, ValueError:
            self.call_from_thread(self.finish_preflight, None)
        else:
            self.call_from_thread(self.finish_preflight, result)

    def finish_preflight(self, result: PublicationPreflight | None) -> None:
        """Show only observed preflight results; failed checks cannot enable consent."""
        self.set_publication_busy(busy=False)
        self.preflight = result
        if result is None:
            self.query_one("#preflight-status", Label).update(
                "Checks could not finish. Verify the token, plan, receipt journal and repository access; then check again."
            )
            self.show_notice("Publication is blocked. Nothing has been published.")
            return
        reused = sum(item.existing is not None for item in result.items)
        blocked = sum(item.error is not None for item in result.items)
        lines = []
        for item in result.items:
            outcome = (
                f"BLOCKED: {item.error}"
                if item.error
                else f"Existing {'PR' if item.existing.route == 'pr' else 'issue'} #{item.existing.number} reused"
                if item.existing
                else "Ready to create · repository route, branch and evidence checks passed"
            )
            lines.append(f"{get_remedy_name(item.remedy_id)}\n  {outcome}")
        self.query_one("#preflight-details", TextArea).load_text("\n\n".join(lines))
        self.query_one("#preflight-status", Label).update(
            f"[ok] Saved proposals and approvals match.    Checked {result.checked_at:%H:%M:%S} UTC\n"
            f"Expected: {len(result.items) - reused - blocked} new · {reused} reused · {blocked} blocked\n"
            "Existing matches require no creation. New writes are checked again during publication."
        )
        allowed = result.can_publish()
        self.query_one("#confirmation", Checkbox).disabled = not allowed
        self.query_one("#publish", Button).disabled = not allowed
        if allowed:
            self.checked_plan = self.plan.model_dump_json()
            self.query_one("#confirmation", Checkbox).focus()
        self.show_notice(
            "Confirm to publish these selections. GitHub may still reject a write."
            if allowed
            else "Resolve blocked checks before publication; completed matches will be reused."
        )

    @on(Button.Pressed, "#back-to-selection")
    @on(Button.Pressed, "#finish-back")
    def return_to_selection(self) -> None:
        """Invalidate confirmation when leaving the publication screen."""
        if not self.busy:
            self.preflight = None
            self.checked_plan = None
            self.query_one("#confirmation", Checkbox).value = False
            self.show_page("selection" if self.plan.bundle else "inspection")
            self.call_after_refresh(self.show_candidates)

    @on(Button.Pressed, "#publish")
    def start_publication(self) -> None:
        """Require successful current-plan preflight and fresh explicit confirmation."""
        if self.busy:
            return
        if (
            not self.preflight
            or not self.preflight.can_publish()
            or self.checked_plan != self.plan.model_dump_json()
        ):
            self.show_notice("Run publication checks again before confirming this plan.")
            return
        if not self.query_one("#confirmation", Checkbox).value:
            self.show_notice("Check the confirmation box to publish these selections.")
            return
        self.results = []
        self.query_one("#results", OptionList).clear_options()
        self.query_one("#result-link", Label).update("")
        self.query_one("#open-result", Button).disabled = True
        self.query_one("#progress", ProgressBar).update(total=len(self.plan.selected), progress=0)
        self.query_one("#publication-title", Label).update("PUBLISHING")
        self.query_one("#publication-checks").display = False
        self.query_one("#publication-results").display = True
        self.query_one("#publish", Button).disabled = True
        self.query_one("#confirmation", Checkbox).disabled = True
        self.set_publication_busy(busy=True)
        self.show_result_counts()
        self.show_notice("Saving each completed result before processing the next remedy.")
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
        label = Text(get_remedy_name(receipt.remedy_id))
        label.truncate(32, overflow="ellipsis", pad=True)
        label.append("  ")
        label.append(
            f"{'Created' if receipt.status == 'created' else 'Existing reused':<18}",
            style="#9DDEAE" if receipt.status == "created" else "#72D5E5",
        )
        label.append("Draft PR" if receipt.route == "pr" else "Issue")
        self.query_one("#results", OptionList).add_option(Option(label))
        if self.query_one("#results", OptionList).highlighted is None:
            self.query_one("#results", OptionList).highlighted = 0
        self.query_one("#progress", ProgressBar).update(progress=len(self.results))
        self.query_one("#open-result", Button).disabled = False
        self.show_result_counts()

    def show_result_counts(self, *, failed: int = 0, unresolved: int = 0) -> None:
        """Distinguish completed results from failed, uncertain and unprocessed work."""
        created = sum(r.status == "created" for r in self.results)
        remaining = len(self.plan.selected) - len(self.results) - failed - unresolved
        self.query_one("#result-counts", Label).update(
            f"Created  {created}    Reused  {len(self.results) - created}    "
            f"Failed / blocked  {failed}    Unresolved  {unresolved}    Remaining  {remaining}"
        )

    def finish_publication(self, journal: ReceiptJournal | None) -> None:
        """Preserve completed results when a later remedy needs reconciliation."""
        self.set_publication_busy(busy=False)
        self.preflight = None
        self.checked_plan = None
        self.query_one("#confirmation", Checkbox).value = False
        failed = unresolved = 0
        if journal is None and len(self.results) < len(self.plan.selected):
            try:
                saved = load_receipts(self.plan.get_receipt_path(self.path), self.plan.report.repository)
                current = saved.receipts.get(self.plan.selected[len(self.results)])
                unresolved = int(current is not None and current.status in {"pending", "uncertain"})
                failed = 1 - unresolved
            except OSError, ValueError:
                unresolved = 1
        self.show_result_counts(failed=failed, unresolved=unresolved)
        self.query_one("#publication-title", Label).update(
            "PUBLICATION COMPLETE" if journal else "PUBLICATION STOPPED"
        )
        self.show_notice(
            f"Results saved: {self.plan.get_receipt_path(self.path).name}. "
            + (
                "Draft PRs await maintainer review; issues await action."
                if journal
                else "Stopped. Inspect receipts, then check again before retrying."
            )
        )
        self.query_one("#results" if self.results else "#check-again").focus()

    @on(OptionList.OptionHighlighted, "#results")
    def show_result_link(self, event: OptionList.OptionHighlighted) -> None:
        """Keep long returned URLs readable without widening every result row."""
        receipt = self.results[event.option_index]
        self.query_one("#result-link", Label).update(
            f"{get_remedy_name(receipt.remedy_id)}\n{receipt.url or ''}"
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
