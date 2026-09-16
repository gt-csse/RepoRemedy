"""Reader evidence, rejected inputs and public command behavior."""

import hashlib
from importlib.metadata import entry_points
import json
from pathlib import Path
import runpy

import pytest
from typer.testing import CliRunner

from RepoRemedy import __version__
from RepoRemedy.cli import app
from RepoRemedy.models import ReportType
from RepoRemedy.readers import read_report
from RepoRemedy.readers.common import ReportError, repository_name

FIXTURES = Path(__file__).parent / "fixtures"
RA = (FIXTURES / "repoauditor.txt").read_text(encoding="utf-8")
RUNNER = CliRunner()


def scan():
    return json.loads((FIXTURES / "scorecard.json").read_text(encoding="utf-8"))


def invoke(tmp_path, data, kind="ossf-scorecard", repo="acme/demo"):
    path = tmp_path / "report.data"
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return RUNNER.invoke(app, ["inspect", str(path), "--report-type", kind, "--repo", repo])


@pytest.mark.parametrize("shape", ["raw", "wrapper", "array", "mixed"])
def test_scorecard_source_and_json_pointer(tmp_path, shape):
    data = scan()
    if shape != "raw":
        data = {"meta": {"contact": "private@example.org"}, "scorecard": data}
    if shape in {"array", "mixed"}:
        data = [data]
    if shape == "mixed":
        other = scan()
        other["repo"]["name"] = "other/repo"
        assert isinstance(data, list)
        data.append(other)
    result = invoke(tmp_path, data)
    assert result.exit_code == 0 and result.stderr == ""
    report = json.loads(result.stdout)
    source = report["source"]
    issue = report["issues"][0]
    assert source["sha256"] == hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest()
    assert source["version"] == "v5.5.0" and source["audited_commit"] == "example-audited-revision"
    assert source["scan_date"] == "2026-07-01T00:00:00Z" and "private@example.org" not in result.stdout
    located = data
    for part in issue["location"].strip("/").split("/"):
        located = located[int(part)] if isinstance(located, list) else located[part]
    assert json.loads(issue["evidence"]) == located and issue["origin"] == "OSSF"
    assert issue["original_status"] is None


@pytest.mark.parametrize("score,status", [(0, "gap"), (9, "gap"), (-1, "unavailable"), (10, None)])
def test_check_status_and_unknown_names(tmp_path, score, status):
    data = scan()
    data["checks"][0].update(score=score, name="Future-Check")
    report = json.loads(invoke(tmp_path, data).stdout)
    assert len(report["issues"]) == (status is not None)
    if status:
        assert report["issues"][0]["status"] == status and report["issues"][0]["check"] == "Future-Check"


def test_repoauditor_provenance(tmp_path):
    result = invoke(tmp_path, "\x1b[31m" + RA + "\x1b[0m", "repoauditor")
    report = json.loads(result.stdout)
    assert [i["status"] for i in report["issues"]] == ["error", "warning"]
    assert [i["original_status"] for i in report["issues"]] == ["Error", "Warning"]
    assert report["issues"][0]["location"] == "lines:2-7"
    assert "Resolution" in report["issues"][0]["evidence"]
    assert report["issues"][0]["origin"] == "RA" and report["source"]["version"] is None
    assert report["notices"] and report["source"]["sha256"]


@pytest.mark.parametrize(
    "message",
    [
        "WARNING: Incomplete data was encountered.\nPlease update the permissions of the GitHub PAT.",
        "WARNING: Incomplete data was encountered.\nGitHub PAT was not provided. Please provide the PAT.",
        "WARNING: Incomplete data was\nencountered.",
    ],
)
@pytest.mark.parametrize("status", ["Warning", "Error"])
def test_repoauditor_unavailable_evidence(tmp_path, message, status):
    message = message.replace("WARNING:", f"{status.upper()}:")
    body = "\n".join(f"│ │ {line} │ │" for line in message.splitlines())
    data = RA.replace("│ │ WARNING: Dependabot security updates are disabled.                   │ │", body)
    data = data.replace("[Warning] DependabotSecurityUpdates", f"[{status}] DependabotSecurityUpdates")
    report = json.loads(invoke(tmp_path, data, "repoauditor").stdout)
    issue = report["issues"][1]
    assert issue["status"] == "unavailable" and issue["original_status"] == status
    assert issue["evidence"] == message and issue["location"].startswith("lines:13-")
    assert report["source"]["sha256"] == hashlib.sha256(data.encode()).hexdigest()


METRICS = """╭─ Metrics ──────────────────╮
│ Successful: 1 (33.33%)     │
│ Warnings: 1 (33.33%)       │
│ Errors: 1 (33.33%)         │
│ Skipped: 0 (0.00%)         │
╰───────────────────────────╯
"""


@pytest.mark.parametrize("data", [RA, "\n".join(RA.splitlines()[:7]), RA + METRICS])
def test_repoauditor_completeness_is_unverified(tmp_path, data):
    result = invoke(tmp_path, data, "repoauditor")
    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert any("Report completeness is unverified" in notice for notice in report["notices"])
    if "Metrics" in data:
        assert "Validated 1 module Metrics panel(s)" in report["notices"][-1]


@pytest.mark.parametrize(
    "metrics",
    [
        METRICS.replace("Warnings: 1", "Warnings: 2"),
        METRICS.replace("Errors: 1", "Errors: 0"),
        METRICS.replace("Successful: 1", "Successful: 0"),
        METRICS.replace("│ Skipped: 0 (0.00%)         │\n", ""),
        METRICS.replace("│ Skipped: 0 (0.00%)         │", "│ Warnings: 1 (33.33%)       │"),
        "\n".join(METRICS.splitlines()[:-1]),
        "╭─ Metrics",
    ],
)
def test_repoauditor_invalid_completion_markers(tmp_path, metrics):
    result = invoke(tmp_path, RA + metrics, "repoauditor")
    assert result.exit_code == 2 and result.stdout == "" and "Error:" in result.stderr


def test_repoauditor_metrics_without_visible_successes(tmp_path):
    data = METRICS.replace("Warnings: 1", "Warnings: 0").replace("Errors: 1", "Errors: 0")
    result = invoke(tmp_path, data, "repoauditor")
    assert result.exit_code == 0 and json.loads(result.stdout)["issues"] == []


def test_repoauditor_metrics_do_not_hide_missing_findings(tmp_path):
    result = invoke(tmp_path, METRICS, "repoauditor")
    assert result.exit_code == 2 and result.stdout == ""


def test_repoauditor_metrics_use_original_status_and_reset_per_module(tmp_path):
    data = RA.replace("Dependabot security updates are disabled.", "Incomplete data was encountered.")
    next_module = METRICS.replace("Warnings: 1", "Warnings: 0").replace("Errors: 1", "Errors: 0")
    result = invoke(tmp_path, data + METRICS + next_module, "repoauditor")
    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["issues"][1]["status"] == "unavailable"
    assert "Validated 2 module Metrics panel(s)" in report["notices"][-1]


@pytest.mark.parametrize(
    "text",
    [
        "Metrics\nSuccessful: 2\nWarnings: 0 (0%)\nErrors: 0 (0%)",
        RA.replace("[Error]", "[Success]").replace("[Warning]", "[DoesNotApply]"),
    ],
)
def test_clean_reports(tmp_path, text):
    assert json.loads(invoke(tmp_path, text, "repoauditor").stdout)["issues"] == []


@pytest.mark.parametrize("repo", ["Acme/Demo", "https://github.com/acme/demo.git/", "github.com/acme/demo"])
def test_identity(repo):
    assert repository_name(repo) == "acme/demo"


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["inspect"],
        ["inspect", "absent"],
        ["inspect", str(FIXTURES)],
        ["inspect", str(FIXTURES / "scorecard.json")],
        ["inspect", str(FIXTURES / "scorecard.json"), "--repo", "acme/demo"],
        ["inspect", str(FIXTURES / "scorecard.json"), "--report-type", "ossf-scorecard"],
    ],
)
def test_required_arguments(args):
    assert RUNNER.invoke(app, args).exit_code == 2


@pytest.mark.parametrize("args", [["--help"], ["inspect", "--help"], ["--version"]])
def test_help_and_version(args):
    result = RUNNER.invoke(app, args)
    assert result.exit_code == 0 and (__version__ if args == ["--version"] else "Usage:") in result.stdout


def test_entrypoint_and_module(monkeypatch):
    assert next(iter(entry_points(group="console_scripts", name="RepoRemedy"))).load() is app
    monkeypatch.setattr("sys.argv", ["RepoRemedy", "--version"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("RepoRemedy", run_name="__main__")
    assert exc.value.code == 0


def test_file_errors_and_explicit_selection(tmp_path, monkeypatch):
    assert invoke(tmp_path, scan(), repo="a/..").exit_code == 2
    assert invoke(tmp_path, scan(), kind="auto").exit_code == 2
    assert invoke(tmp_path, scan(), kind="repoauditor").exit_code == 2
    path = tmp_path / "report.data"
    path.write_bytes(b"\xff")
    for file, kind in [
        (path, ReportType.SCORECARD),
        (tmp_path / "missing", ReportType.SCORECARD),
        (path, "auto"),
    ]:
        with pytest.raises(ReportError):
            read_report(file, kind, "a/b")
    monkeypatch.setattr("RepoRemedy.readers.MAX_BYTES", 1)
    path.write_bytes(b"123")
    with pytest.raises(ReportError, match="limit"):
        read_report(path, ReportType.SCORECARD, "a/b")


@pytest.mark.parametrize("case", json.loads((FIXTURES / "invalid_reports.json").read_text(encoding="utf-8")))
def test_invalid_reports(tmp_path, case):
    result = invoke(tmp_path, case["data"], case["kind"])
    assert result.exit_code == 2 and result.stdout == "" and "Error:" in result.stderr
