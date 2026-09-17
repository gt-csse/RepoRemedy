"""Reader evidence, rejected inputs and public command behavior."""

import hashlib
import datetime
from importlib.metadata import entry_points
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic_core import PydanticSerializationError
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


def invoke(tmp_path, data, kind="ossf-scorecard", repo="acme/demo", *, newline=None):
    path = tmp_path / "report.data"
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8", newline=newline)
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


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("2026-07-01", datetime.date(2026, 7, 1)),
        ("2026-07-01T00:00:00Z", datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)),
        ("2026-07-01T12:34:56+02:00", datetime.datetime.fromisoformat("2026-07-01T12:34:56+02:00")),
    ],
)
def test_typed_source_preserves_date_precision_and_json(tmp_path, value, expected):
    data = scan()
    data["date"] = value
    result = invoke(tmp_path, data)
    assert result.exit_code == 0 and json.loads(result.stdout)["source"]["scan_date"] == value
    report = read_report(tmp_path / "report.data", ReportType.SCORECARD, "acme/demo")
    assert report.source.path == (tmp_path / "report.data").resolve()
    assert report.source.scan_date == expected and type(report.source.scan_date) is type(expected)


@pytest.mark.parametrize("value", ["", "yesterday", "2026-02-30", 1782864000, True, {}, []])
def test_invalid_scan_dates(tmp_path, value):
    data = scan()
    data["date"] = value
    result = invoke(tmp_path, data)
    assert result.exit_code == 2 and result.stdout == "" and "date" in result.stderr


@pytest.mark.parametrize("field", ["name", "reason"])
def test_scorecard_text_must_contain_non_whitespace(tmp_path, field):
    data = scan()
    data["checks"][0][field] = " \t\n "
    result = invoke(tmp_path, data)
    assert result.exit_code == 2 and result.stdout == ""


@pytest.mark.parametrize("version", ["v4.0.0", "v6.0.0"])
def test_unsupported_scorecard_major_versions(tmp_path, version):
    data = scan()
    data["scorecard"]["version"] = version
    assert invoke(tmp_path, data).exit_code == 2


@pytest.mark.parametrize("kind", ["repoauditor", "ossf-scorecard"])
@pytest.mark.parametrize(
    "repo",
    [
        "https://github.gatech.edu/sse-center/sse-resources",
        "github.gatech.edu/sse-center/sse-resources",
    ],
)
def test_enterprise_reports_preserve_host(tmp_path, kind, repo):
    data = scan()
    data["repo"]["name"] = "https://GITHUB.GATECH.EDU/SSE-Center/SSE-Resources.git/"
    result = invoke(tmp_path, RA if kind == "repoauditor" else data, kind, repo)
    assert result.exit_code == 0 and result.stderr == ""
    assert json.loads(result.stdout)["repository"] == "github.gatech.edu/sse-center/sse-resources"


def test_scorecard_selects_repository_on_correct_host(tmp_path):
    public, enterprise, other = scan(), scan(), scan()
    enterprise["repo"].update(name="github.gatech.edu/acme/demo", commit="enterprise-revision")
    other["repo"].update(name="https://github.example.org/acme/demo", commit="other-revision")
    result = invoke(tmp_path, [public, enterprise, other], repo="https://github.gatech.edu/acme/demo.git")
    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["source"]["audited_commit"] == "enterprise-revision"
    assert report["issues"][0]["location"] == "/1/checks/0"


@pytest.mark.parametrize(
    "source,target",
    [
        ("acme/demo", "https://github.gatech.edu/acme/demo"),
        ("github.gatech.edu/acme/demo", "acme/demo"),
        ("github.gatech.edu/acme/demo", "https://github.example.org/acme/demo"),
        ("github.gatech.edu:8443/acme/demo", "https://github.gatech.edu/acme/demo"),
    ],
)
def test_scorecard_rejects_cross_host_matches(tmp_path, source, target):
    data = scan()
    data["repo"]["name"] = source
    result = invoke(tmp_path, data, repo=target)
    assert result.exit_code == 2 and result.stdout == ""
    assert "exactly one scan matching the repository" in result.stderr


@pytest.mark.parametrize("failure", ["serialization", "output"])
def test_cli_output_failures(tmp_path, monkeypatch, failure):
    if failure == "serialization":
        report = MagicMock()
        report.model_dump_json.side_effect = PydanticSerializationError("sensitive detail")
        monkeypatch.setattr("RepoRemedy.cli.read_report", lambda *_: report)
    else:
        from RepoRemedy.cli import typer

        echo = typer.echo

        def fail_stdout(message, **kwargs):
            if not kwargs.get("err"):
                raise OSError("sensitive detail")
            return echo(message, **kwargs)

        monkeypatch.setattr(typer, "echo", fail_stdout)
    result = invoke(tmp_path, scan())
    assert result.exit_code == 2 and result.stdout == ""
    assert (
        "Cannot serialize or write report output" in result.stderr and "sensitive detail" not in result.stderr
    )


@pytest.mark.parametrize("initial_size", [0, 3], ids=["growing-file", "already-oversized"])
def test_size_guard_before_read_and_after_growth(tmp_path, monkeypatch, initial_size):
    stream = MagicMock()
    stream.__enter__.return_value = stream
    stream.read.return_value = b"123"
    monkeypatch.setattr(Path, "open", lambda *_: stream)
    monkeypatch.setattr("RepoRemedy.readers.MAX_BYTES", 2)
    monkeypatch.setattr("RepoRemedy.readers.os.fstat", lambda _: SimpleNamespace(st_size=initial_size))
    with pytest.raises(ReportError, match="limit"):
        read_report(tmp_path / "report.data", ReportType.SCORECARD, "acme/demo")
    if initial_size:
        stream.read.assert_not_called()
    else:
        stream.read.assert_called_once_with(3)


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
@pytest.mark.parametrize("newline", [None, "\n", "\r\n"], ids=["native", "lf", "crlf"])
def test_repoauditor_unavailable_evidence(tmp_path, message, status, newline):
    message = message.replace("WARNING:", f"{status.upper()}:")
    body = "\n".join(f"│ │ {line} │ │" for line in message.splitlines())
    data = RA.replace("│ │ WARNING: Dependabot security updates are disabled.                   │ │", body)
    data = data.replace("[Warning] DependabotSecurityUpdates", f"[{status}] DependabotSecurityUpdates")
    report = json.loads(invoke(tmp_path, data, "repoauditor", newline=newline).stdout)
    issue = report["issues"][1]
    assert issue["status"] == "unavailable" and issue["original_status"] == status
    assert issue["evidence"] == message and issue["location"].startswith("lines:13-")
    assert report["source"]["sha256"] == hashlib.sha256((tmp_path / "report.data").read_bytes()).hexdigest()


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
    "repo,expected",
    [
        ("https://GITHUB.GATECH.EDU/Acme/Demo.git/", "github.gatech.edu/acme/demo"),
        ("github.gatech.edu/acme/demo", "github.gatech.edu/acme/demo"),
        ("https://git.corp/acme/demo", "git.corp/acme/demo"),
        ("https://github.gatech.edu:8443/acme/demo", "github.gatech.edu:8443/acme/demo"),
        ("github.gatech.edu:08443/acme/demo", "github.gatech.edu:8443/acme/demo"),
        ("https://github.gatech.edu:443/acme/demo", "github.gatech.edu/acme/demo"),
        ("https://github.com:443/acme/demo", "acme/demo"),
    ],
)
def test_host_identity_normalization(repo, expected):
    assert repository_name(repo) == expected
    assert repository_name(expected) == expected


@pytest.mark.parametrize(
    "repo",
    [
        "https://github.gatech.edu/acme/demo?ref=main",
        "https://github.gatech.edu/acme/demo#readme",
        "https://user:secret@github.gatech.edu/acme/demo",
        "https://github.gatech.edu/acme/demo/tree/main",
        "https://github.gatech.edu/acme/%2e%2e",
        "https://github.gatech.edu/acme/..",
        "https://github.gatech.edu/acme-/demo",
        "https://github.gatech.edu:0/acme/demo",
        "https://github.gatech.edu:65536/acme/demo",
        "https://-github.gatech.edu/acme/demo",
        "https://github..gatech.edu/acme/demo",
        "https:///acme/demo",
        "https://github.gatech.edu/acme/demo\n",
        "http://github.gatech.edu/acme/demo",
    ],
)
def test_invalid_repository_identities(repo):
    with pytest.raises(ReportError):
        repository_name(repo)


def test_subcommand_help():
    result = RUNNER.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "inspect" in result.stdout and "command" in result.stdout.lower()
    result = RUNNER.invoke(app, ["inspect", "--help"])
    assert result.exit_code == 0 and "report" in result.stdout.lower()


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
        [str(FIXTURES / "scorecard.json"), "--report-type", "ossf-scorecard", "--repo", "acme/demo"],
    ],
)
def test_required_arguments(args):
    assert RUNNER.invoke(app, args).exit_code == 2


@pytest.mark.parametrize("args", [["--help"], ["--version"]])
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
