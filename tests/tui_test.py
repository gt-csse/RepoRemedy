"""Exercise real Textual controls and publication against the simulated GitHub API."""

import asyncio

import httpx
import pytest
from textual.widgets import (
    Button,
    Checkbox,
    ContentSwitcher,
    Input,
    Label,
    OptionList,
    RichLog,
    Select,
    SelectionList,
    TextArea,
)

from publication_fixtures import PublishingGitHub
from remedy_fixtures import make_report
from plan_test import make_plan, approve_plan
from RepoRemedy.catalog import load_catalog
from RepoRemedy.context.github import ContextError
from RepoRemedy.plan import RemedyPlan, load_plan
from RepoRemedy.review import InputScreen, ReviewScreen
from RepoRemedy.propose import propose_remedies
from RepoRemedy.tui import RemedyApp


def install_api(monkeypatch, api):
    real_client = httpx.Client
    monkeypatch.setattr(
        "RepoRemedy.tui.httpx.Client", lambda **kw: real_client(transport=httpx.MockTransport(api))
    )
    monkeypatch.setenv("REPOREMEDY_TOKEN", "test")


async def wait_for_worker(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()


def test_inspect_select_inputs_review_save_resume_publish_retry(tmp_path, monkeypatch):
    api = PublishingGitHub()
    install_api(monkeypatch, api)
    plan = RemedyPlan(report=make_report())
    path = tmp_path / "plan.json"

    async def exercise():
        app = RemedyApp(plan, path)
        async with app.run_test(size=(140, 45)) as pilot:
            assert app.query_one("#pages", ContentSwitcher).current == "inspection"
            assert not api.requests
            await pilot.click("#continue")
            await wait_for_worker(app, pilot)
            assert app.query_one("#pages", ContentSwitcher).current == "selection"
            assert "Evidence: SecurityPolicy" in app.query_one("#details", TextArea).text
            choices = app.query_one("#candidates", SelectionList)
            choices.focus()
            await pilot.press("space")
            assert plan.selected == ["security-policy"]
            await pilot.click("#prepare-publication")
            assert app.query_one("#pages", ContentSwitcher).current == "selection"
            await pilot.click("#review")
            assert isinstance(app.screen, ReviewScreen)
            assert app.screen.query_one("#approve", Button).disabled
            await pilot.click("#edit")
            await pilot.pause()
            assert isinstance(app.screen, InputScreen)
            form = app.screen
            assert {"security_reporting_instructions", "supported_versions"} <= set(form.fields)
            await pilot.click("#generate")
            assert isinstance(app.screen, InputScreen)  # explicit input approval required
            for i, field in enumerate(form.fields):
                form.query_one(f"#input-{i}", TextArea).load_text(
                    "1.x" if field == "supported_versions" else "Use the private reporting form"
                )
            form.query_one("#approve-inputs", Checkbox).value = True
            await pilot.pause(0.3)
            await pilot.click("#generate")
            await pilot.pause()
            assert isinstance(app.screen, ReviewScreen)
            assert not app.screen.query_one("#approve", Button).disabled
            assert "SECURITY.md" in "\n".join(
                line.text for line in app.screen.query_one("#preview", RichLog).lines
            )
            await pilot.click("#approve")
            await pilot.pause()
            assert plan.is_reviewed("security-policy")
            assert app.query_one("#pages", ContentSwitcher).current == "review-complete"
            app.action_save()
            assert load_plan(path).reviewed == plan.reviewed
            assert not api.posts
            await pilot.press("ctrl+q")
        restored = load_plan(path)
        app = RemedyApp(restored, path, publish_only=True)
        async with app.run_test(size=(140, 45)) as pilot:
            await wait_for_worker(app, pilot)
            assert app.preflight is not None and app.preflight.can_publish() and not api.posts
            await pilot.click("#publish")
            assert not api.posts
            app.query_one("#confirmation", Checkbox).value = True
            await pilot.pause(0.3)
            await pilot.click("#publish")
            await wait_for_worker(app, pilot)
            assert len(api.issues) == 1 and api.issues[0]["draft"]
            assert app.results[0].status == "created"
            await pilot.click("#check-again")
            await wait_for_worker(app, pilot)
            app.query_one("#confirmation", Checkbox).value = True
            await pilot.pause(0.3)
            await pilot.click("#publish")
            await wait_for_worker(app, pilot)
            assert len(api.issues) == 1 and app.results[0].status == "existing"
            opened = []
            monkeypatch.setattr("RepoRemedy.tui.webbrowser.open", opened.append)
            await pilot.click("#open-result")
            assert opened == [app.results[0].url]
            await pilot.click("#back-to-selection")
            assert app.query_one("#pages", ContentSwitcher).current == "selection"

    asyncio.run(exercise())


def test_select_30_of_40_filter_and_clear_preserve_hidden_selections(tmp_path):
    api = PublishingGitHub()
    report = make_report()
    report.issues = [
        make_report(remedy.sources["RA"][0]).issues[0]
        for remedy in load_catalog().remedies.values()
        if remedy.sources.get("RA")
    ][:40]
    plan = RemedyPlan(report=report)
    with httpx.Client(transport=httpx.MockTransport(api)) as client:
        plan.collect(client)

    async def exercise():
        app = RemedyApp(plan, tmp_path / "plan.json")
        async with app.run_test(size=(140, 45)) as pilot:
            assert len(app.visible_indices) == 40
            await pilot.click("#select-filtered")
            assert len(plan.selected) == 40
            for identifier in list(plan.selected)[-10:]:
                plan.set_selected(identifier, selected=False)
            app.show_candidates()
            assert len(plan.selected) == 30
            saved = list(plan.selected)
            app.query_one("#search", Input).value = saved[0]
            await pilot.pause()
            visible = {plan.get_proposals()[i].remedy_id for i in app.visible_indices}
            await pilot.click("#clear-filtered")
            assert set(plan.selected) == set(saved) - visible
            await pilot.click("#select-filtered")
            assert set(plan.selected) == set(saved)
            app.query_one("#search", Input).value = ""
            app.query_one("#filter", Select).value = "Selected"
            await pilot.pause()
            assert len(app.visible_indices) == 30
            app.query_one("#filter", Select).value = "Ready"
            await pilot.pause()
            assert all(plan.get_proposals()[i].status == "ready" for i in app.visible_indices)
            app.query_one("#filter", Select).value = "Needs input"
            await pilot.pause()
            assert all(plan.get_proposals()[i].status == "needs-input" for i in app.visible_indices)

    asyncio.run(exercise())


def test_collection_failure_save_failure_and_busy_exit(tmp_path, monkeypatch):
    plan = RemedyPlan(report=make_report())

    def fail(*args):
        raise ContextError("PRIVATE")

    monkeypatch.setattr(RemedyPlan, "collect", fail)

    async def exercise():
        app = RemedyApp(plan, tmp_path / "missing" / "plan.json")
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.click("#continue")
            await wait_for_worker(app, pilot)
            assert app.query_one("#pages", ContentSwitcher).current == "inspection"
            assert "PRIVATE" not in str(app.query_one("#notice", Label).content)
            assert not app.persist()
            app.busy = True
            await app.action_quit()
            app.action_save()
            app.busy = False

    asyncio.run(exercise())


def test_review_cancel_deselect_and_publish_failure(tmp_path, monkeypatch):
    plan, api = make_plan()
    install_api(monkeypatch, api)

    async def exercise():
        app = RemedyApp(plan, tmp_path / "plan.json")
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.click("#review")
            plan.set_selected("security-policy", selected=True)
            await pilot.pause(0.3)
            await pilot.click("#review")
            await pilot.click("#edit")
            await pilot.click("#cancel-inputs")
            await pilot.click("#back")
            await pilot.click("#review")
            await pilot.click("#deselect")
            assert plan.selected == []
            approve_plan(plan)
            await pilot.click("#prepare-publication")
            await wait_for_worker(app, pilot)
            api.overrides[("GET", "/issues")] = httpx.Response(403)
            app.query_one("#confirmation", Checkbox).value = True
            await pilot.click("#publish")
            await wait_for_worker(app, pilot)
            assert not api.posts and not app.busy
            assert not app.query_one("#confirmation", Checkbox).value
            assert "Stopped" in str(app.query_one("#notice", Label).content)
            assert load_plan(tmp_path / "plan.json").selected == ["security-policy"]

    asyncio.run(exercise())


def test_partial_publication_retains_receipts_and_reconciles_lost_response(tmp_path, monkeypatch):
    api = PublishingGitHub()
    report = make_report()
    report.issues.append(make_report("RequireApprovals").issues[0])
    bundle = propose_remedies(
        report,
        api.snapshot(),
        {"ra-require-approvals": {"approved_value": "3", "reported_expected_value": "3"}},
        approved_inputs={"ra-require-approvals"},
        route="issue",
    )
    plan = RemedyPlan(report=report, bundle=bundle)
    for identifier in ["security-policy", "ra-require-approvals"]:
        plan.set_selected(identifier, selected=True)
        plan.approve(identifier)
    install_api(monkeypatch, api)
    key = ("POST", "/issues")

    def lose_second_response(request):
        del api.overrides[key]
        response = api(request)
        api.overrides[key] = lose_second_response
        if len(api.issues) == 2:
            raise httpx.ReadTimeout("PRIVATE", request=request)
        return response

    api.overrides[key] = lose_second_response

    async def exercise():
        app = RemedyApp(plan, tmp_path / "plan.json", publish_only=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await wait_for_worker(app, pilot)
            app.query_one("#confirmation", Checkbox).value = True
            await pilot.click("#publish")
            await wait_for_worker(app, pilot)
            assert len(app.results) == 1 and len(api.issues) == 2
            assert "Stopped" in str(app.query_one("#notice", Label).content)
            assert "PRIVATE" not in str(app.query_one("#notice", Label).content)
            assert "Unresolved  1" in str(app.query_one("#result-counts", Label).content)
            del api.overrides[key]
            await pilot.click("#check-again")
            await wait_for_worker(app, pilot)
            app.query_one("#confirmation", Checkbox).value = True
            await pilot.pause(0.3)
            await pilot.click("#publish")
            await wait_for_worker(app, pilot)
            assert len(api.posts) == 2
            assert [r.status for r in app.results] == ["existing", "existing"]

    asyncio.run(exercise())


@pytest.mark.parametrize("size", [(120, 40), (80, 24)])
def test_keyboard_selection_search_resize_and_review(tmp_path, size):
    plan, _ = make_plan()

    async def exercise():
        app = RemedyApp(plan, tmp_path / "plan.json")
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await pilot.press("a")
            assert plan.selected == ["security-policy"]
            await pilot.press("/")
            assert app.focused is app.query_one("#search")
            await pilot.press("f", "a")
            assert app.query_one("#search", Input).value == "fa"
            assert plan.selected == ["security-policy"]
            assert app.visible_indices == []
            assert "No matching remedies" in app.query_one("#details", TextArea).text
            app.query_one("#search", Input).value = ""
            await pilot.press("escape")
            assert app.focused is app.query_one("#candidates")
            assert "Evidence: SecurityPolicy" in app.query_one("#details", TextArea).text
            await pilot.press("f")
            assert app.focused is app.query_one("#filter")
            app.query_one("#candidates").focus()
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            assert "compact" in app.screen.classes
            viewport = app.screen.region
            for identifier in ("candidates", "details", "review", "prepare-publication", "save-exit"):
                assert viewport.contains_region(app.query_one(f"#{identifier}").region)
            await pilot.press("enter")
            assert isinstance(app.screen, ReviewScreen)
            await pilot.press("e")
            assert isinstance(app.screen, InputScreen)
            await pilot.press("escape")
            assert isinstance(app.screen, ReviewScreen)
            await pilot.press("enter")
            assert plan.is_reviewed("security-policy")
            assert app.query_one("#pages", ContentSwitcher).current == "review-complete"
            await pilot.press("escape")
            assert app.query_one("#pages", ContentSwitcher).current == "selection"

    asyncio.run(exercise())


@pytest.mark.parametrize("choice", [0, 1, 2, 3])
def test_resume_choices_do_not_publish(tmp_path, monkeypatch, choice):
    plan, api = make_plan()
    approve_plan(plan)
    install_api(monkeypatch, api)
    path = tmp_path / "plan.json"

    async def exercise():
        app = RemedyApp(plan, path, resumed=True)
        async with app.run_test(size=(80, 24)) as pilot:
            assert app.query_one("#pages", ContentSwitcher).current == "resume"
            api.requests.clear()
            assert not api.requests
            app.query_one("#resume-options", OptionList).highlighted = choice
            await pilot.press("enter")
            await wait_for_worker(app, pilot)
            if choice == 0:
                assert app.preflight is not None and app.preflight.can_publish()
                assert not app.query_one("#confirmation", Checkbox).value
            elif choice == 1:
                assert isinstance(app.screen, ReviewScreen)
                await pilot.press("escape")
            elif choice == 2:
                assert app.query_one("#pages", ContentSwitcher).current == "selection"
            else:
                assert load_plan(path).selected == plan.selected
            assert not api.posts

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["access", "token", "changed_plan"])
def test_preflight_blocks_confirmation_and_rechecks_after_failure(tmp_path, monkeypatch, failure):
    plan, api = make_plan()
    approve_plan(plan)
    install_api(monkeypatch, api)
    if failure == "access":
        api.overrides[("GET", "/issues")] = httpx.Response(403)
    elif failure == "token":
        monkeypatch.delenv("REPOREMEDY_TOKEN")

    async def exercise():
        app = RemedyApp(plan, tmp_path / "plan.json", publish_only=True)
        async with app.run_test(size=(100, 36)) as pilot:
            await wait_for_worker(app, pilot)
            if failure == "changed_plan":
                plan.reviewed.clear()
            else:
                assert app.query_one("#confirmation", Checkbox).disabled
                assert app.query_one("#publish", Button).disabled
            app.query_one("#confirmation", Checkbox).value = True
            app.start_publication()
            assert not api.posts
            approve_plan(plan)
            api.overrides.clear()
            monkeypatch.setenv("REPOREMEDY_TOKEN", "test")
            await pilot.click("#check-again")
            await wait_for_worker(app, pilot)
            assert app.preflight is not None and app.preflight.can_publish()
            assert not app.query_one("#confirmation", Checkbox).value
            assert not (tmp_path / "publication-receipts.json").exists()

    asyncio.run(exercise())
