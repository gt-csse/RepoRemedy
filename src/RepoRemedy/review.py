# noqa: CPY001
"""Textual forms and exact-content preview; all remedy logic lives in the plan."""

from typing import TYPE_CHECKING

from textual import on
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, Select, TextArea

from RepoRemedy.catalog import load_catalog
from RepoRemedy.context.github import ContextError

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from RepoRemedy.plan import RemedyPlan


def render_proposal(plan: RemedyPlan, identifier: str) -> str:
    """Present untrusted source text literally, including reasons, body and file diffs."""
    proposal = plan.get_proposal(identifier)
    lines = [f"{identifier} / {proposal.route} / {proposal.status}", "", "Evidence"]
    lines.extend(f"{f.origin} {f.check} ({f.location}): {f.evidence}" for f in proposal.findings)
    lines.extend(["", *proposal.reasons])
    lines.extend(f"Required: {key} - {reason}" for key, reason in proposal.missing_inputs.items())
    if proposal.content:
        lines.extend(["", proposal.content.title, "", proposal.content.body])
        for file in proposal.content.files:
            lines.extend(["", file.path.as_posix(), file.diff])
    return "\n".join(lines)


class InputScreen(ModalScreen[bool]):
    """Use library text areas for multiline catalog inputs and explicit approval."""

    def __init__(self, plan: RemedyPlan, identifier: str) -> None:
        super().__init__()
        self.plan = plan
        self.identifier = identifier
        self.fields: list[str] = []

    def compose(self) -> ComposeResult:
        """Compose library controls for the current review step."""
        with VerticalScroll(id="dialog"):
            yield Label(f"Inputs: {self.identifier}", markup=False)
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
            await container.mount(Label(name.replace("_", " "), markup=False))
            await container.mount(TextArea(value, id=f"input-{index}", classes="input-field"))
        self.query_one("#approve-inputs", Checkbox).value = False

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

    def __init__(self, plan: RemedyPlan) -> None:
        super().__init__()
        self.plan = plan
        self.identifiers = list(plan.selected)
        self.index = 0

    def compose(self) -> ComposeResult:
        """Compose library controls for the current review step."""
        with VerticalScroll(id="dialog"):
            yield Label(id="review-position", markup=False)
            yield TextArea(read_only=True, id="preview")
            with Horizontal(classes="buttons"):
                yield Button("Approve / next", id="approve", variant="primary")
                yield Button("Edit inputs / route", id="edit")
                yield Button("Deselect", id="deselect")
                yield Button("Back", id="back")

    def on_mount(self) -> None:
        """Show the first selected proposal."""
        self.show_proposal()

    def show_proposal(self, _changed: bool | None = None) -> None:  # noqa: FBT001 - modal callback
        """Display the exact body and diff that approval will bind to."""
        identifier = self.identifiers[self.index]
        proposal = self.plan.get_proposal(identifier)
        self.query_one("#review-position", Label).update(
            f"Review {self.index + 1}/{len(self.identifiers)}: {identifier} ({proposal.status})"
        )
        self.query_one("#preview", TextArea).load_text(render_proposal(self.plan, identifier))
        self.query_one("#approve", Button).disabled = proposal.status != "ready"

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        """Delegate input and content validation to the shared plan model."""
        identifier = self.identifiers[self.index]
        match event.button.id:
            case "back":
                self.dismiss(None)
            case "edit":
                self.app.push_screen(InputScreen(self.plan, identifier), self.show_proposal)
            case "approve" | "deselect":
                try:
                    if event.button.id == "approve":
                        self.plan.approve(identifier)
                    else:
                        self.plan.set_selected(identifier, selected=False)
                except ContextError, ValueError:
                    self.notify(
                        "Proposal validation failed; edit inputs or regenerate context", severity="error"
                    )
                    return
                self.index += 1
                if self.index == len(self.identifiers):
                    self.dismiss(None)
                else:
                    self.show_proposal()
