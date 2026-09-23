# noqa: CPY001
"""Textual forms and exact-content preview; all remedy logic lives in the plan."""

from typing import TYPE_CHECKING, ClassVar

from rich.text import Text

from textual import on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Footer, Label, RichLog, Select, TextArea

from RepoRemedy.catalog import load_catalog
from RepoRemedy.context.github import ContextError

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from RepoRemedy.plan import RemedyPlan


def get_remedy_name(identifier: str) -> str:
    """Display a readable catalog identifier without maintaining a parallel catalog."""
    return identifier.removeprefix("ra-").replace("-", " ").capitalize()


def render_proposal(plan: RemedyPlan, identifier: str) -> str:
    """Present untrusted source text literally, including reasons, body and file diffs."""
    proposal = plan.get_proposal(identifier)
    route = "Draft PR" if proposal.route == "pr" else "Issue"
    lines = [f"{get_remedy_name(identifier)}  /  {route}  /  {proposal.status}"]
    if proposal.content:
        lines.extend(["", f"Title: {proposal.content.title}"])
    lines.extend(["", "Evidence"])
    lines.extend(f"{f.origin} {f.check} ({f.location}): {f.evidence}" for f in proposal.findings)
    lines.extend(proposal.reasons)
    lines.extend(f"Required: {key} - {reason}" for key, reason in proposal.missing_inputs.items())
    if proposal.content:
        for file in proposal.content.files:
            lines.extend(["", f"New file: {file.path.as_posix()}", file.diff])
        lines.extend(
            [
                "",
                "## PR description" if proposal.route == "pr" else "## Issue body",
                "",
                proposal.content.body,
            ]
        )
    return "\n".join(lines)


class InputScreen(ModalScreen[bool]):
    """Use library text areas for multiline catalog inputs and explicit approval."""

    BINDINGS: ClassVar = [("escape", "cancel", "Back"), ("ctrl+enter", "generate", "Generate preview")]

    def __init__(self, plan: RemedyPlan, identifier: str) -> None:
        super().__init__()
        self.plan = plan
        self.identifier = identifier
        self.fields: list[str] = []

    def compose(self) -> ComposeResult:
        """Compose library controls for the current review step."""
        with Vertical(id="dialog"):
            yield Label(
                f"{get_remedy_name(self.identifier).upper()}  /  COMPLETE INPUTS",
                id="input-title",
                markup=False,
            )
            options = [("Issue", "issue")]
            if load_catalog().remedies[self.identifier].pr:
                options.append(("Draft PR", "pr"))
            yield Select(
                options, value=self.plan.get_proposal(self.identifier).route, allow_blank=False, id="route"
            )
            yield VerticalScroll(id="fields")
            yield Checkbox("I approve these inputs for this repository", id="approve-inputs")
            with Horizontal(classes="buttons"):
                yield Button("Generate preview", id="generate", variant="primary")
                yield Button("Cancel", id="cancel-inputs")
            yield Footer(show_command_palette=False)

    @on(Select.Changed, "#route")
    async def show_fields(self) -> None:
        """Rebuild only the input form when the user changes publication route."""
        route = self.query_one("#route", Select).value
        assert route in {"issue", "pr"}
        values = self.plan.get_editable_inputs(self.identifier, route)
        self.fields = list(values)
        container = self.query_one("#fields", VerticalScroll)
        await container.remove_children()
        for index, (name, value) in enumerate(values.items()):
            await container.mount(
                Label(name.replace("_", " ").capitalize(), markup=False, classes="field-name")
            )
            await container.mount(TextArea(value, id=f"input-{index}", classes="input-field"))
        self.query_one("#approve-inputs", Checkbox).value = False

    def action_generate(self) -> None:
        """Generate through the same approval gate as the button."""
        self.generate_preview()

    def action_cancel(self) -> None:
        """Leave form values unapplied when returning to the preview."""
        self.cancel_inputs()

    @on(Button.Pressed, "#generate")
    def generate_preview(self) -> None:
        """Approve values separately from the later exact-content review."""
        if not self.query_one("#approve-inputs", Checkbox).value:
            self.notify("Confirm the input values before generating a preview", severity="warning")
            return
        route = self.query_one("#route", Select).value
        assert route in {"issue", "pr"}
        values = {name: self.query_one(f"#input-{i}", TextArea).text for i, name in enumerate(self.fields)}
        try:
            self.plan.update_inputs(self.identifier, route, values)
        except ContextError, ValueError:
            self.notify("Fill all fields with valid values; preview was not approved", severity="error")
        else:
            self.dismiss(result=True)

    @on(Button.Pressed, "#cancel-inputs")
    def cancel_inputs(self) -> None:
        """Leave the current proposal and approval unchanged."""
        self.dismiss(result=False)


class ReviewScreen(ModalScreen[None]):
    """Review each selected issue or PR, retaining selection and input controls."""

    BINDINGS: ClassVar = [
        ("enter", "approve", "Approve / next"),
        ("e", "edit", "Edit inputs"),
        ("d", "deselect", "Deselect"),
        ("escape", "back", "Back"),
    ]

    def __init__(self, plan: RemedyPlan) -> None:
        super().__init__()
        self.plan = plan
        self.identifiers = list(plan.selected)
        self.index = 0

    def compose(self) -> ComposeResult:
        """Compose library controls for the current review step."""
        with Vertical(id="dialog"):
            yield Label(id="review-position", markup=False)
            yield RichLog(wrap=True, markup=False, auto_scroll=False, min_width=1, id="preview")
            with Horizontal(classes="buttons"):
                yield Button("Approve / next", id="approve", variant="primary")
                yield Button("Edit inputs / route", id="edit")
                yield Button("Deselect", id="deselect")
                yield Button("Back", id="back")
            yield Label(
                "Approval applies to this exact preview. Publication requires separate confirmation.",
                classes="muted",
            )
            yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        """Show the first selected proposal."""
        self.show_proposal()
        self.query_one("#preview", RichLog).focus()

    def show_proposal(self, _changed: bool | None = None) -> None:  # noqa: FBT001 - modal callback
        """Display the exact body and diff that approval will bind to."""
        identifier = self.identifiers[self.index]
        proposal = self.plan.get_proposal(identifier)
        self.query_one("#review-position", Label).update(
            f"REVIEW {self.index + 1} / {len(self.identifiers)}    {identifier}    "
            f"{'Draft PR' if proposal.route == 'pr' else 'Issue'} / {proposal.status}"
        )
        preview = Text()
        for line in render_proposal(self.plan, identifier).splitlines():
            style = (
                "#9DDEAE"
                if line.startswith("+")
                else "#F08C8C"
                if line.startswith("-")
                else "bold #72D5E5"
                if line.startswith(("#", "Title:", "New file:", "@@")) or line == "Evidence"
                else ""
            )
            preview.append(line + "\n", style=style)
        self.query_one("#preview", RichLog).clear().write(preview)
        self.query_one("#preview", RichLog).scroll_home(animate=False)
        self.query_one("#approve", Button).disabled = proposal.status != "ready"

    def action_approve(self) -> None:
        """Approve exact content using the shared plan validator."""
        self.advance_review(deselect=False)

    def action_edit(self) -> None:
        """Edit the current remedy's inputs and route."""
        self.app.push_screen(InputScreen(self.plan, self.identifiers[self.index]), self.show_proposal)

    def action_deselect(self) -> None:
        """Remove the current remedy from the saved selection."""
        self.advance_review(deselect=True)

    def action_back(self) -> None:
        """Return without approving the current preview."""
        self.dismiss(None)

    def advance_review(self, *, deselect: bool) -> None:
        """Advance only after validation or an explicit deselection."""
        identifier = self.identifiers[self.index]
        try:
            if deselect:
                self.plan.set_selected(identifier, selected=False)
            else:
                self.plan.approve(identifier)
        except ContextError, ValueError:
            self.notify("Proposal validation failed; edit inputs or regenerate context", severity="error")
            return
        self.index += 1
        if self.index == len(self.identifiers):
            self.dismiss(None)
        else:
            self.show_proposal()

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        """Use the same actions for keyboard and mouse navigation."""
        match event.button.id:
            case "back":
                self.action_back()
            case "edit":
                self.action_edit()
            case "approve":
                self.action_approve()
            case "deselect":
                self.action_deselect()
