"""Propose command invocation, input boundaries and error reporting."""

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from RepoRemedy.cli import app
from RepoRemedy.context.github import ContextError
from remedy_fixtures import make_report
from repository_context_test import COMMIT, FakeGitHub

RUNNER = CliRunner()
AUDIT = Path(__file__).parent / "fixtures/repoauditor.txt"


@pytest.mark.parametrize("repository", ["acme/demo", "https://github.example:8443/acme/demo"])
def test_cli_propose_collects_and_renders_without_writing_to_github(monkeypatch, repository):
    api = FakeGitHub()
    real_client = httpx.Client
    monkeypatch.setattr(
        "RepoRemedy.cli.httpx.Client", lambda **kwargs: real_client(transport=httpx.MockTransport(api))
    )
    result = RUNNER.invoke(app, ["propose", str(AUDIT), "--report-type", "repoauditor", "--repo", repository])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["context"]["commit_sha"] == COMMIT and data["proposals"]
    assert all(r.method == "GET" for r in api.requests)
    if "github.example" in repository:
        assert data["repository"] == "github.example:8443/acme/demo"
        assert all(r.url.host == "github.example" and r.url.port == 8443 for r in api.requests)
        assert all(r.url.path.startswith("/api/v3/") for r in api.requests)
    assert all("content" in p for p in data["proposals"])
    assert "PRIVATE" not in result.stdout
    help_result = RUNNER.invoke(app, ["--help"])
    assert "propose" in help_result.stdout and "resolve-inputs" not in help_result.stdout
    assert RUNNER.invoke(app, ["context"]).exit_code == 2


def test_cli_recorded_commit_default_and_explicit_ref_and_token(monkeypatch):
    source = make_report(commit=COMMIT)
    monkeypatch.setattr("RepoRemedy.workflow.read_report", lambda *args: source)
    captured = {}
    context = FakeGitHub().snapshot()

    def collect(repo, client, **kwargs):
        captured.update(kwargs)
        return context

    monkeypatch.setattr("RepoRemedy.workflow.collect_context", collect)
    monkeypatch.setenv("ENTERPRISE_TOKEN", "PRIVATE")
    args = [
        "propose",
        str(AUDIT),
        "--report-type",
        "repoauditor",
        "--repo",
        "https://github.example/acme/demo",
        "--token-env",
        "ENTERPRISE_TOKEN",
    ]
    result = RUNNER.invoke(app, args)
    assert result.exit_code == 0 and "PRIVATE" not in result.stdout
    assert captured == {"ref": COMMIT, "token": "PRIVATE"}
    assert RUNNER.invoke(app, [*args, "--ref", "main"]).exit_code == 0
    assert captured["ref"] == "main"


@pytest.mark.parametrize("failure", [ContextError("Cannot resolve branch"), OSError("PRIVATE")])
def test_cli_errors_do_not_leak_response_details(monkeypatch, failure):
    def collect(*args, **kwargs):
        raise failure

    monkeypatch.setattr("RepoRemedy.workflow.collect_context", collect)
    result = RUNNER.invoke(
        app, ["propose", str(AUDIT), "--report-type", "repoauditor", "--repo", "acme/demo"]
    )
    assert result.exit_code == 2 and result.stdout == "" and "PRIVATE" not in result.stderr


@pytest.mark.parametrize(
    "content,success",
    [
        ("not-json", False),
        ("[" * 2000 + "]" * 2000, False),
        ("[]", False),
        ('{"unknown": {}}', False),
        ('{"ra-license-file": {"approved_license_text": "MIT"}}', True),
    ],
)
def test_cli_input_files(monkeypatch, tmp_path, content, success):
    context = FakeGitHub().snapshot()
    monkeypatch.setattr("RepoRemedy.workflow.collect_context", lambda *args, **kwargs: context)
    supplied = tmp_path / "inputs.json"
    supplied.write_text(content)
    result = RUNNER.invoke(
        app,
        [
            "propose",
            str(AUDIT),
            "--report-type",
            "repoauditor",
            "--repo",
            "acme/demo",
            "--inputs",
            str(supplied),
        ],
    )
    assert result.exit_code == (0 if success else 2), result.output


def test_cli_size_limit_precedes_network(monkeypatch, tmp_path):
    supplied = tmp_path / "inputs.json"
    with supplied.open("wb") as file:
        file.truncate(2 * 1024 * 1024)

    def unexpected(*args, **kwargs):
        pytest.fail("Should not collect context")

    monkeypatch.setattr("RepoRemedy.workflow.collect_context", unexpected)
    result = RUNNER.invoke(
        app,
        [
            "propose",
            str(AUDIT),
            "--report-type",
            "repoauditor",
            "--repo",
            "acme/demo",
            "--inputs",
            str(supplied),
        ],
    )
    assert result.exit_code == 2 and "size limit" in result.stderr


def test_cli_renders_approved_pr_in_one_invocation(monkeypatch, tmp_path):
    context = FakeGitHub().snapshot()
    monkeypatch.setattr("RepoRemedy.workflow.collect_context", lambda *args, **kwargs: context)
    supplied = tmp_path / "inputs.json"
    supplied.write_text(
        json.dumps(
            {
                "security-policy": {
                    "supported_versions": "1.x",
                    "security_reporting_instructions": "Use the private reporting form",
                }
            }
        )
    )
    result = RUNNER.invoke(
        app,
        [
            "propose",
            str(AUDIT),
            "--report-type",
            "repoauditor",
            "--repo",
            "acme/demo",
            "--inputs",
            str(supplied),
            "--approve-inputs",
            "security-policy",
            "--route",
            "pr",
        ],
    )
    assert result.exit_code == 0, result.output
    proposal = json.loads(result.stdout)["proposals"][0]
    assert proposal["route"] == "pr" and proposal["status"] == "ready"
    assert proposal["content"]["files"][0]["path"] == "SECURITY.md"
    assert "Use the private reporting form" in proposal["content"]["files"][0]["content"]
