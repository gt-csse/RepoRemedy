"""Single/batch parity, multi-repository isolation, and durable partial results."""

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from typer.testing import CliRunner

from RepoRemedy.batch import BatchManifest, ReportResult, RepositoryResult, run_batch
import RepoRemedy.cli as cli
from RepoRemedy.cli import app
from RepoRemedy.context import collect_context
from RepoRemedy.context.github import ContextError
from RepoRemedy.readers.common import repository_name
import RepoRemedy.workflow as workflow
from repository_context_test import COMMIT, FakeGitHub

RUNNER = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


def setup_batch(tmp_path, monkeypatch, count=5):
    jobs, snapshots, calls = [], {}, []
    for index in range(count):
        name = f"Acme/Repo{index}"
        key = repository_name(name)
        folder = tmp_path / name
        folder.mkdir(parents=True)
        (folder / "repoauditor.txt").write_bytes((FIXTURES / "repoauditor.txt").read_bytes())
        scorecard = json.loads((FIXTURES / "scorecard.json").read_text())
        scorecard["repo"] = {"name": name, "commit": COMMIT}
        (folder / "ossf-scorecard.json").write_text(json.dumps(scorecard))
        context = FakeGitHub().snapshot()
        context.repository = key
        context.observations["repository"].value["full_name"] = key
        snapshots[key] = context
        jobs.append({"repository": name})

    def collect(repository, client, **kwargs):
        calls.append((repository, kwargs))
        return snapshots[repository]

    monkeypatch.setattr("RepoRemedy.workflow.collect_context", collect)
    data = {
        "schema_version": 1,
        "reports": [
            {"report_type": "repoauditor", "path": "{owner}/{repo}/{report_type}.txt"},
            {"report_type": "ossf-scorecard", "path": "{owner}/{repo}/{report_type}.json"},
        ],
        "repositories": jobs,
    }
    manifest = tmp_path / "batch.json"
    manifest.write_text(json.dumps(data))
    return manifest, data, calls


def invoke(manifest, output):
    return RUNNER.invoke(app, ["propose-batch", str(manifest), "--output", str(output)])


@pytest.mark.parametrize("count", [5, 10])
def test_real_readers_and_shared_proposals_match_single_for_every_repository(tmp_path, monkeypatch, count):
    manifest, data, calls = setup_batch(tmp_path, monkeypatch, count)
    output = tmp_path / "results"
    monkeypatch.chdir(tmp_path.parent)  # Templates resolve relative to manifest, not cwd.
    result = invoke(manifest, output)
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary == json.loads((output / "summary.json").read_text())
    assert summary["planned_repositories"] == count and summary["planned_reports"] == count * 2
    assert summary["status"] == "completed" and summary["exit_code"] == 0
    assert summary["succeeded_reports"] == count * 2 and summary["failed_reports"] == 0
    assert [call[1]["ref"] for call in calls] == ["main", COMMIT] * count
    for index, job in enumerate(data["repositories"], 1):
        saved_summary = json.loads((output / f"{index:04d}/summary.json").read_text())
        assert saved_summary == summary["repositories"][index - 1]
        for report_type, suffix in [("repoauditor", "txt"), ("ossf-scorecard", "json")]:
            source = tmp_path / job["repository"] / f"{report_type}.{suffix}"
            single = RUNNER.invoke(
                app, ["propose", str(source), "--report-type", report_type, "--repo", job["repository"]]
            )
            assert single.exit_code == 0, single.output
            saved = json.loads((output / f"{index:04d}/{report_type}.proposals.json").read_text())
            assert saved == json.loads(single.stdout)
            item = next(r for r in saved_summary["reports"] if r["report_type"] == report_type)
            assert item["report_sha256"] == saved["report_sha256"]
            assert item["base_commit"] == COMMIT
            assert sum(item["proposal_statuses"].values()) == len(saved["proposals"])


@pytest.mark.parametrize(
    "problem", ["missing", "malformed", "identity", "context", "inputs", "nested_inputs"]
)
def test_middle_failure_keeps_earlier_and_later_artifacts(tmp_path, monkeypatch, problem):
    manifest, data, calls = setup_batch(tmp_path, monkeypatch)
    report = tmp_path / "Acme/Repo2/repoauditor.txt"
    if problem == "missing":
        report.unlink()
    elif problem == "malformed":
        report.write_text("SECRET invalid report")
    elif problem == "identity":
        data["repositories"][2]["repository"] = "https://user:SECRET@github.com/acme/repo2"
    elif problem == "inputs":
        data["repositories"][2]["inputs"] = "missing-inputs.json"
    elif problem == "nested_inputs":
        data["repositories"][2]["inputs"] = "nested.json"
        (tmp_path / "nested.json").write_text("[" * 2000 + "]" * 2000)
    else:
        original = workflow.collect_context

        def collect(repository, client, **kwargs):
            if repository == "acme/repo2":
                raise ContextError("SECRET")
            return original(repository, client, **kwargs)

        monkeypatch.setattr("RepoRemedy.workflow.collect_context", collect)
    manifest.write_text(json.dumps(data))
    output = tmp_path / "results"
    result = invoke(manifest, output)
    assert result.exit_code == 3 and "SECRET" not in result.output
    summary = json.loads(result.stdout)
    assert summary["exit_code"] == 3 and summary["status"] == "completed"
    for directory in ("0001", "0002", "0004", "0005"):
        assert (output / directory / "repoauditor.proposals.json").exists()
    failed = summary["repositories"][2]
    assert failed["reports"][0]["status"] == "failed"
    assert not (output / "0003/repoauditor.proposals.json").exists()
    if problem in {"missing", "malformed"}:
        assert failed["reports"][1]["status"] == "succeeded"
    assert "SECRET" not in (output / "0003/summary.json").read_text()


def test_options_and_host_tokens_are_isolated_and_shared_with_single(tmp_path, monkeypatch):
    manifest, data, calls = setup_batch(tmp_path, monkeypatch, 2)
    data["reports"] = data["reports"][:1]
    data["repositories"][0].update(
        repository="https://github.example:8443/Acme/Repo0.GIT",
        ref="release",
        inputs="{owner}/{repo}/inputs.json",
        route="pr",
        approve_inputs=["security-policy"],
        token_env="ENTERPRISE_TOKEN",
    )
    supplied = tmp_path / "Acme/Repo0/inputs.json"
    supplied.write_text(
        json.dumps(
            {
                "security-policy": {
                    "supported_versions": "1.x",
                    "security_reporting_instructions": "Contact maintainers privately",
                }
            }
        )
    )
    monkeypatch.setenv("ENTERPRISE_TOKEN", "SECRET_ENTERPRISE")
    monkeypatch.setenv("REPOREMEDY_TOKEN", "SECRET_PUBLIC")
    snapshot = FakeGitHub().snapshot()
    seen = []

    def collect(repository, client, **kwargs):
        context = snapshot.model_copy(deep=True)
        context.repository = repository
        context.observations["repository"].value["full_name"] = "/".join(repository.split("/")[-2:])
        seen.append((repository, kwargs))
        return context

    monkeypatch.setattr("RepoRemedy.workflow.collect_context", collect)
    manifest.write_text(json.dumps(data))
    output = tmp_path / "results"
    result = invoke(manifest, output)
    assert result.exit_code == 0, result.output
    assert seen == [
        ("github.example:8443/acme/repo0", {"ref": "release", "token": "SECRET_ENTERPRISE"}),
        ("acme/repo1", {"ref": "main", "token": "SECRET_PUBLIC"}),
    ]
    first = json.loads((output / "0001/repoauditor.proposals.json").read_text())
    second = json.loads((output / "0002/repoauditor.proposals.json").read_text())
    assert first["proposals"][0]["status"] == "ready" and first["proposals"][0]["route"] == "pr"
    assert second["approved_inputs"] == []
    single = RUNNER.invoke(
        app,
        [
            "propose",
            str(tmp_path / "Acme/Repo0/repoauditor.txt"),
            "--report-type",
            "repoauditor",
            "--repo",
            data["repositories"][0]["repository"],
            "--ref",
            "release",
            "--inputs",
            str(supplied),
            "--route",
            "pr",
            "--approve-inputs",
            "security-policy",
            "--token-env",
            "ENTERPRISE_TOKEN",
        ],
    )
    assert single.exit_code == 0 and json.loads(single.stdout) == first
    assert not any("SECRET_" in file.read_text() for file in output.rglob("*.json"))


def test_all_inputs_fail_and_existing_output_is_never_overwritten(tmp_path, monkeypatch):
    manifest, data, calls = setup_batch(tmp_path, monkeypatch, 1)
    data["repositories"][0]["repository"] = "bad"
    manifest.write_text(json.dumps(data))
    output = tmp_path / "results"
    result = invoke(manifest, output)
    assert result.exit_code == 2 and json.loads(result.stdout)["exit_code"] == 2
    original = (output / "summary.json").read_bytes()
    assert invoke(manifest, output).exit_code == 2
    assert (output / "summary.json").read_bytes() == original and not calls


@pytest.mark.parametrize("change", ["empty", "type", "duplicate", "unknown", "template", "syntax", "inputs"])
def test_invalid_manifest_fails_before_network_or_output(tmp_path, monkeypatch, change):
    manifest, data, calls = setup_batch(tmp_path, monkeypatch, 1)
    if change == "empty":
        data["repositories"] = []
    elif change == "type":
        data["reports"][0]["report_type"] = "unknown"
    elif change == "duplicate":
        data["reports"] *= 2
    elif change == "unknown":
        data["repository"] = "typo"
    elif change == "template":
        data["reports"][0]["path"] = "{owner.__class__}"
    elif change == "syntax":
        data["reports"][0]["path"] = "{repo"
    else:
        data["repositories"][0]["inputs"] = "{unknown}"
    manifest.write_text(json.dumps(data))
    output = tmp_path / "results"
    assert invoke(manifest, output).exit_code == 2
    assert not output.exists() and not calls


@pytest.mark.parametrize("grows_after_size_check", [False, True])
def test_large_manifest_is_rejected(tmp_path, monkeypatch, track_file_reads, grows_after_size_check):
    manifest = tmp_path / "batch.json"
    with manifest.open("wb") as stream:
        stream.truncate(1024 * 1024 + 1)
    tracked = track_file_reads(manifest)
    if grows_after_size_check:
        monkeypatch.setattr("RepoRemedy.batch.os.fstat", lambda fd: SimpleNamespace(st_size=0))
    assert invoke(manifest, tmp_path / "results").exit_code == 2
    if grows_after_size_check:
        tracked.read.assert_called_once_with(1024 * 1024 + 1)
    else:
        tracked.read.assert_not_called()
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize("length", [40, 64])
def test_summary_paths_and_commit_round_trip(length):
    report = ReportResult(
        report_type="repoauditor", artifact=Path("0001/repoauditor.proposals.json"), base_commit="A" * length
    )
    summary = RepositoryResult(position=1, directory=Path("0001"), reports=[report])
    assert isinstance(summary.directory, Path) and isinstance(report.artifact, Path)
    encoded = json.loads(summary.model_dump_json())
    assert encoded["directory"] == "0001"
    assert encoded["reports"][0]["artifact"] == "0001/repoauditor.proposals.json"
    assert encoded["reports"][0]["base_commit"] == "a" * length
    assert RepositoryResult.model_validate_json(summary.model_dump_json()) == summary


@pytest.mark.parametrize("commit", ["a" * 39, "g" * 40, "a" * 41, "a" * 40 + "\n"])
def test_summary_commit_uses_shared_validation(commit):
    with pytest.raises(ValueError):
        ReportResult(report_type="repoauditor", base_commit=commit)


@pytest.mark.parametrize("failure", ["bundle", "repository_summary", "root_summary"])
def test_write_failure_preserves_progress_and_cleans_temporary_files(tmp_path, monkeypatch, failure):
    manifest, data, calls = setup_batch(tmp_path, monkeypatch, 3)
    output = tmp_path / "results"
    original = Path.replace

    def replace(path, target):
        target = Path(target)
        if (
            failure == "bundle"
            and target == output / "0002/repoauditor.proposals.json"
            or failure == "repository_summary"
            and target == output / "0002/summary.json"
            or failure == "root_summary"
            and target == output / "summary.json"
            and (output / "0002/summary.json").exists()
        ):
            raise OSError("SECRET filesystem details")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    result = invoke(manifest, output)
    assert result.exit_code == (2 if failure == "root_summary" else 3)
    assert "SECRET" not in result.output
    assert (output / "0001/repoauditor.proposals.json").exists()
    if failure != "root_summary":
        assert (output / "0003/repoauditor.proposals.json").exists()
    else:
        checkpoint = json.loads((output / "summary.json").read_text())
        assert checkpoint["status"] == "running" and checkpoint["exit_code"] is None
        assert len(checkpoint["repositories"]) == 1 and checkpoint["succeeded_reports"] == 2
        assert (output / "0002/repoauditor.proposals.json").exists()
        assert not (output / "0003").exists()
    assert not list(output.rglob("tmp*"))


@pytest.mark.parametrize("missing_report", [False, True])
def test_stdout_failure_preserves_completed_summary_and_bundles(tmp_path, monkeypatch, missing_report):
    manifest, data, calls = setup_batch(tmp_path, monkeypatch, 1)
    if missing_report:
        (tmp_path / "Acme/Repo0/repoauditor.txt").unlink()
    output = tmp_path / "results"
    original = cli.typer.echo

    def echo(message, *, err=False):
        if not err:
            raise OSError("SECRET stdout failure")
        original(message, err=err)

    monkeypatch.setattr(cli.typer, "echo", echo)
    result = invoke(manifest, output)
    assert result.exit_code == 2 and "SECRET" not in result.output
    saved = json.loads((output / "summary.json").read_text())
    assert saved["status"] == "completed" and saved["exit_code"] == (3 if missing_report else 0)
    artifact = saved["repositories"][0]["reports"][1]["artifact"]
    assert json.loads((output / artifact).read_text())["base_commit"] == COMMIT


def test_duplicate_repositories_are_separate_runs_and_do_not_publish(tmp_path, monkeypatch):
    manifest, data, calls = setup_batch(tmp_path, monkeypatch, 1)
    data["repositories"] *= 2
    data["reports"] = data["reports"][:1]
    manifest.write_text(json.dumps(data))
    api = FakeGitHub()
    monkeypatch.setattr("RepoRemedy.workflow.collect_context", collect_context)
    # Use a fixture repository the simulated API recognizes.
    data["repositories"] = [{"repository": "acme/demo"}] * 2
    data["reports"][0]["path"] = str(FIXTURES / "repoauditor.txt")
    manifest.write_text(json.dumps(data))
    with httpx.Client(transport=httpx.MockTransport(api)) as client:
        summary = run_batch(manifest, tmp_path / "results", client)
    assert summary.exit_code == 0
    assert summary.repositories[0].directory != summary.repositories[1].directory
    assert all(request.method == "GET" for request in api.requests)


def test_demo_manifest_processes_twenty_existing_reports(tmp_path, monkeypatch):
    manifest = Path(__file__).resolve().parents[1] / "demo/batch.json"
    config = BatchManifest.model_validate_json(manifest.read_bytes())
    assert len(config.repositories) == 10 and len(config.reports) == 2
    snapshot = FakeGitHub().snapshot()

    def collect(repository, client, *, ref, token):
        context = snapshot.model_copy(deep=True)
        context.repository = repository
        context.commit_sha = ref
        context.requested_ref = ref
        context.observations["repository"].value["full_name"] = repository
        return context

    monkeypatch.setattr("RepoRemedy.workflow.collect_context", collect)
    result = invoke(manifest, tmp_path / "demo-results")
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    reports = [report for repo in summary["repositories"] for report in repo["reports"]]
    assert len(reports) == 20 and all(report["status"] == "succeeded" for report in reports)
    assert all(report["report_sha256"] and report["base_commit"] for report in reports)
