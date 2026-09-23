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
