"""CLI adapters preserve JSON commands and never publish an unconfirmed plan."""

import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from typer.testing import CliRunner
from rich.text import Text

from plan_test import approve_plan, make_plan
from RepoRemedy.cli import app
from RepoRemedy.context.github import ContextError
from RepoRemedy.interactive import run_inspection, run_plan_publication
from RepoRemedy.plan import load_plan, save_plan

RUNNER = CliRunner()
REPORT = Path(__file__).parent / "fixtures/repoauditor.txt"


def test_json_inspect_and_explicit_interactive_adapter(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("RepoRemedy.cli.run_inspection", lambda *args, **kwargs: calls.append((args, kwargs)))
    args = ["inspect", str(REPORT), "--report-type", "repoauditor", "--repo", "acme/demo"]
    result = RUNNER.invoke(app, args)
    assert result.exit_code == 0 and json.loads(result.stdout)["repository"] == "acme/demo"
    assert not calls
    result = RUNNER.invoke(app, args + ["--interactive", "--plan", str(tmp_path / "session.json")])
    assert result.exit_code == 0 and result.stdout == ""
    assert calls[0][0][1] == tmp_path / "session.json"


def test_terminal_inspection_new_and_resume(tmp_path, monkeypatch):
    plan, _ = make_plan()
    path = tmp_path / "session.json"
    monkeypatch.setattr("RepoRemedy.interactive.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("RepoRemedy.interactive.sys.stdout.isatty", lambda: True)
    ui = Mock()
    monkeypatch.setattr("RepoRemedy.tui.RemedyApp", ui)
    run_inspection(plan.report, path, token_env="ENTERPRISE_TOKEN")
    assert ui.call_args.args[0].token_env == "ENTERPRISE_TOKEN"
    assert ui.return_value.run.call_count == 1
    assert ui.call_args.kwargs == {"resumed": False}
    save_plan(plan, path)
    with pytest.raises(ContextError, match="already exists"):
        run_inspection(plan.report, path)
    run_inspection(None, path, resume=True)
    assert ui.call_args.args[0] == load_plan(path)
    assert ui.call_args.kwargs == {"resumed": True}
    monkeypatch.setattr("RepoRemedy.cli.run_inspection", Mock())
    assert RUNNER.invoke(app, ["inspect", "--resume", str(path)]).exit_code == 0
    conflict = RUNNER.invoke(app, ["inspect", str(REPORT), "--resume", str(path)])
    assert conflict.exit_code == 2


def test_nonterminal_never_opens_tui_or_writes(tmp_path, monkeypatch):
    plan, _ = make_plan()
    approve_plan(plan)
    path = tmp_path / "plan.json"
    save_plan(plan, path)
    monkeypatch.setattr("RepoRemedy.interactive.sys.stdin.isatty", lambda: False)
    with pytest.raises(ContextError, match="terminal"):
        run_inspection(plan.report, path)
    with pytest.raises(ContextError, match="confirmation"):
        run_plan_publication(path)
    assert not (tmp_path / "publication-receipts.json").exists()


def test_plan_publication_terminal_and_confirmed_json(tmp_path, monkeypatch):
    plan, api = make_plan()
    approve_plan(plan)
    path = tmp_path / "plan.json"
    save_plan(plan, path)
    monkeypatch.setattr("RepoRemedy.interactive.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("RepoRemedy.interactive.sys.stdout.isatty", lambda: True)
    ui = Mock()
    monkeypatch.setattr("RepoRemedy.tui.RemedyApp", ui)
    assert run_plan_publication(path) is None
    assert ui.call_args.kwargs == {"publish_only": True}
    assert not api.posts
    real_client = httpx.Client
    monkeypatch.setattr(
        "RepoRemedy.interactive.httpx.Client", lambda **kw: real_client(transport=httpx.MockTransport(api))
    )
    monkeypatch.setenv("REPOREMEDY_TOKEN", "PRIVATE")
    result = RUNNER.invoke(app, ["publish", "--plan", str(path), "--confirm"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["receipts"]["security-policy"]["status"] == "created"
    assert "PRIVATE" not in path.read_text()
    monkeypatch.setattr("RepoRemedy.cli.run_plan_publication", lambda *a, **kw: None)
    assert RUNNER.invoke(app, ["publish", "--plan", str(path)]).exit_code == 0


@pytest.mark.parametrize(
    "extra", [["--repo", "other/repo"], ["--select", "security-policy"], ["--token-env", "OTHER_TOKEN"]]
)
def test_plan_rejects_legacy_overrides(tmp_path, extra):
    plan, _ = make_plan()
    path = tmp_path / "plan.json"
    save_plan(plan, path)
    result = RUNNER.invoke(app, ["publish", "--plan", str(path), *extra])
    assert result.exit_code == 2


@pytest.mark.parametrize("args", [["inspect"], ["publish"], ["inspect", str(REPORT)]])
def test_missing_arguments_are_usage_errors(args):
    assert RUNNER.invoke(app, args).exit_code == 2


def test_bad_resume_does_not_disclose_plan_content(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text("PRIVATE")
    monkeypatch.setattr("RepoRemedy.interactive.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("RepoRemedy.interactive.sys.stdout.isatty", lambda: True)
    result = RUNNER.invoke(app, ["inspect", "--resume", str(path)])
    assert result.exit_code == 2 and "PRIVATE" not in result.output


def test_interactive_ref_is_saved_and_cannot_override_resume(tmp_path, monkeypatch):
    plan, _ = make_plan()
    path = tmp_path / "session.json"
    monkeypatch.setattr("RepoRemedy.interactive.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("RepoRemedy.interactive.sys.stdout.isatty", lambda: True)
    ui = Mock()
    monkeypatch.setattr("RepoRemedy.tui.RemedyApp", ui)
    run_inspection(plan.report, path, ref="release/1.x")
    created = ui.call_args.args[0]
    assert created.ref == "release/1.x"
    save_plan(created, path)
    run_inspection(None, path, resume=True)
    assert ui.call_args.args[0].ref == "release/1.x"
    with pytest.raises(ContextError, match="target ref"):
        run_inspection(None, path, resume=True, ref="other")
    result = RUNNER.invoke(app, ["inspect", "--resume", str(path), "--ref", "other"])
    assert result.exit_code == 2 and "--ref" in Text.from_ansi(result.output).plain


def test_cli_ref_requires_interactive_and_is_forwarded(tmp_path, monkeypatch):
    calls = Mock()
    monkeypatch.setattr("RepoRemedy.cli.run_inspection", calls)
    args = ["inspect", str(REPORT), "--report-type", "repoauditor", "--repo", "acme/demo", "--ref", "trunk"]
    result = RUNNER.invoke(app, args)
    assert result.exit_code == 2 and not calls.called
    result = RUNNER.invoke(app, [*args, "--interactive", "--plan", str(tmp_path / "session.json")])
    assert result.exit_code == 0, result.output
    assert calls.call_args.kwargs["ref"] == "trunk"
