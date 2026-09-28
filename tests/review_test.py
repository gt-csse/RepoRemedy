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


def test_save_and_exit_from_input_form_restores_unapproved_draft(tmp_path):
    from RepoRemedy.plan import load_plan
    from textual.widgets import Button

    plan, _ = make_plan()
    approve_plan(plan)
    path = tmp_path / "session.json"

    async def exercise():
        app = RemedyApp(plan, path)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert await pilot.click("#review")
            await pilot.press("e")
            form = app.screen
            assert isinstance(form, InputScreen)
            form.query_one("#route", Select).value = "pr"
            await pilot.pause()
            for index, field in enumerate(form.fields):
                if field == "supported_versions":
                    form.query_one(f"#input-{index}", TextArea).load_text("")
                elif field == "security_reporting_instructions":
                    form.query_one(f"#input-{index}", TextArea).load_text("Unfinished reporting policy")
            await pilot.press("ctrl+s")
            saved = load_plan(path)
            assert saved.drafts["security-policy"].values["supported_versions"] == ""
            assert not saved.is_reviewed("security-policy")
            assert app.screen is form
            await pilot.press("ctrl+q")
            assert not app.is_running
        restored = load_plan(path)
        app = RemedyApp(restored, path)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert await pilot.click("#review")
            assert app.screen.query_one("#approve", Button).disabled
            await pilot.press("enter")
            assert not restored.is_reviewed("security-policy")
            await pilot.press("e")
            form = app.screen
            assert isinstance(form, InputScreen)
            assert form.query_one("#route", Select).value == "pr"
            for index, field in enumerate(form.fields):
                if field == "supported_versions":
                    assert form.query_one(f"#input-{index}", TextArea).text == ""
                    form.query_one(f"#input-{index}", TextArea).load_text("1.x")
                elif field == "security_reporting_instructions":
                    assert form.query_one(f"#input-{index}", TextArea).text == "Unfinished reporting policy"
            form.query_one("#approve-inputs", Checkbox).value = True
            await pilot.press("ctrl+enter")
            assert not restored.drafts and not restored.is_reviewed("security-policy")
            await pilot.press("enter")
            assert restored.is_reviewed("security-policy")

    asyncio.run(exercise())


def test_review_modal_saves_and_exits_without_leaving_dialog(tmp_path):
    from RepoRemedy.plan import load_plan

    plan, _ = make_plan()
    approve_plan(plan)
    path = tmp_path / "session.json"

    async def exercise():
        app = RemedyApp(plan, path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert await pilot.click("#review")
            await pilot.press("ctrl+s")
            assert load_plan(path).is_reviewed("security-policy")
            assert isinstance(app.screen, ReviewScreen)
            await pilot.press("ctrl+q")
            assert not app.is_running

    asyncio.run(exercise())


def test_saved_draft_can_be_discarded_without_approving_it(tmp_path):
    plan, _ = make_plan()
    approve_plan(plan)
    values = plan.get_editable_inputs("security-policy", "issue")
    values["verification_steps"] = "Incomplete draft"
    plan.save_input_draft("security-policy", "issue", values)

    async def exercise():
        app = RemedyApp(plan, tmp_path / "session.json")
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert await pilot.click("#review")
            await pilot.press("e")
            await pilot.click("#discard-draft")
            assert not plan.drafts and not plan.is_reviewed("security-policy")
            await pilot.press("enter")
            assert plan.is_reviewed("security-policy")

    asyncio.run(exercise())


def test_form_save_failure_keeps_draft_and_dialog_open(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("RepoRemedy.tui.save_plan", fail)
    plan, _ = make_plan()
    approve_plan(plan)

    async def exercise():
        app = RemedyApp(plan, tmp_path / "session.json")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert await pilot.click("#review")
            await pilot.press("e")
            form = app.screen
            assert isinstance(form, InputScreen)
            form.query_one("#input-0", TextArea).load_text("Unfinished edit")
            await pilot.press("ctrl+q")
            assert app.is_running and app.screen is form
            assert plan.drafts and not plan.is_reviewed("security-policy")

    asyncio.run(exercise())
