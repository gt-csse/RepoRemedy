"""Review dialogs keep input approval separate from exact content approval."""

import asyncio

from textual.widgets import Checkbox, Select, TextArea

from plan_test import make_plan, approve_plan
from RepoRemedy.context.github import ContextError
from RepoRemedy.plan import RemedyPlan
from RepoRemedy.review import InputScreen, ReviewScreen
from RepoRemedy.tui import RemedyApp


def test_input_route_change_and_invalid_values_leave_review_unapproved(tmp_path):
    plan, _ = make_plan()
    approve_plan(plan)
    before = plan.model_dump_json()

    async def exercise():
        app = RemedyApp(plan, tmp_path / "plan.json")
        async with app.run_test(size=(100, 36)) as pilot:
            app.push_screen(InputScreen(plan, "security-policy"))
            await pilot.pause()
            form = app.screen
            assert isinstance(form, InputScreen)
            form.query_one("#route", Select).value = "pr"
            await pilot.pause()
            assert "supported_versions" in form.fields
            form.query_one("#approve-inputs", Checkbox).value = True
            # Empty required input must not mutate an already approved plan.
            form.query_one("#input-0", TextArea).load_text("")
            await pilot.click("#generate")
            assert isinstance(app.screen, InputScreen)
            assert plan.model_dump_json() == before
            await pilot.click("#cancel-inputs")

    asyncio.run(exercise())


def test_review_validation_failure_keeps_current_preview(tmp_path, monkeypatch):
    plan, _ = make_plan()
    plan.set_selected("security-policy", selected=True)

    def fail(*args):
        raise ContextError("Validation failed")

    monkeypatch.setattr(RemedyPlan, "approve", fail)

    async def exercise():
        app = RemedyApp(plan, tmp_path / "plan.json")
        async with app.run_test(size=(100, 36)) as pilot:
            app.push_screen(ReviewScreen(plan))
            await pilot.pause()
            await pilot.click("#approve")
            assert isinstance(app.screen, ReviewScreen)
            assert not plan.reviewed

    asyncio.run(exercise())


def test_form_typing_does_not_trigger_review_or_selection_shortcuts(tmp_path):
    plan, _ = make_plan()
    approve_plan(plan)
    selected = list(plan.selected)

    async def exercise():
        app = RemedyApp(plan, tmp_path / "plan.json")
        async with app.run_test(size=(80, 24)) as pilot:
            app.push_screen(ReviewScreen(plan))
            await pilot.pause()
            await pilot.press("e")
            assert isinstance(app.screen, InputScreen)
            form = app.screen
            form.query_one("#route", Select).value = "pr"
            await pilot.pause()
            field = form.query_one("#input-0", TextArea)
            field.load_text("")
            field.focus()
            await pilot.press("e", "d", "a", "f", "slash", "enter")
            assert field.text == "edaf/\n"
            assert plan.selected == selected
            assert app.screen is form
            await pilot.press("escape")
            assert isinstance(app.screen, ReviewScreen)
            assert app.screen.region.contains_region(app.screen.query_one("#approve").region)
            assert app.screen.region.contains_region(app.screen.query_one("#back").region)

    asyncio.run(exercise())
