"""Exercise the demo runner with local fake tools; never contact GitHub."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

SPEC = importlib.util.spec_from_file_location(
    "demo_audits", Path(__file__).parents[1] / "demo/scripts/run_audits.py"
)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
pytestmark = pytest.mark.skipif(os.name != "posix", reason="Demo runner supports Linux/macOS")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    tool = tmp_path / "fake-tool"
    tool.write_text(
        f"#!{sys.executable}\n"
        + """
import json, os, pathlib, sys, time
if sys.argv[1] in ('--version', 'version'):
    expected = 'version' if pathlib.Path(__file__).name == 'scorecard' else '--version'
    assert sys.argv[1] == expected
    print('fake 1.0'); sys.exit(0)
if os.environ.get('FAKE_TIMEOUT'):
    time.sleep(60)
print('tool stderr', file=sys.stderr)
if '--output' in sys.argv:
    path = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
    path.write_text(('╭─ Metrics ─╮\\n╰───────────╯\\n') * 3)
    print('tool stdout')
    if '--GitHub-pat' in sys.argv:
        token = pathlib.Path(sys.argv[sys.argv.index('--GitHub-pat') + 1])
        assert token.stat().st_mode & 0o777 == 0o600
        assert 'GITHUB_TOKEN' not in os.environ
        if os.environ.get('FAKE_LEAK'):
            print(token.read_text())
    sys.exit(255)
repo = next(arg.split('=', 1)[1] for arg in sys.argv if arg.startswith('--repo='))
marker = pathlib.Path(__file__).parent / repo.replace('/', '_')
if os.environ.get('FAKE_RETRY') and not marker.exists():
    marker.touch(); sys.exit(1)
print(json.dumps({'repo': {'name': repo}, 'checks': [{'name': 'Example', 'score': -1}]}))
""",
        encoding="utf-8",
    )
    tool.chmod(0o700)
    scorecard = tmp_path / "scorecard"
    scorecard.write_bytes(tool.read_bytes())
    scorecard.chmod(0o700)
    source = tmp_path / "repos.json"
    source.write_text('["acme/demo", "acme/second"]', encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_TOKEN", "test-credential-never-publish")
    monkeypatch.setattr(RUNNER, "metadata", lambda *_: {"default_branch": "develop"})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_audits",
            str(source),
            "--output",
            str(output),
            "--repoauditor",
            str(tool),
            "--scorecard",
            str(scorecard),
        ],
    )
    return source, output


def test_batch_artifacts_and_provenance(setup):
    _, output = setup
    assert RUNNER.main() == 0
    manifest = json.loads((output / "manifest.json").read_text())
    assert len(manifest["repositories"]) == 2
    for repo in manifest["repositories"]:
        assert repo["default_branch"] == "develop"
        for tool in ("repoauditor", "scorecard"):
            result = repo[tool]
            assert result["status"] == "report_written" and result["reader_validation"] == "not_performed"
            assert result["sha256"] == hashlib.sha256((output / result["report"]).read_bytes()).hexdigest()
        assert repo["repoauditor"]["exit_code"] == 255
        log = (output / repo["repoauditor"]["log"]).read_text()
        assert "tool stdout" in log and "tool stderr" in log
    assert all(
        b"test-credential-never-publish" not in p.read_bytes() for p in output.rglob("*") if p.is_file()
    )


def test_preserves_existing_output(setup):
    _, output = setup
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("original")
    with pytest.raises(SystemExit) as exc:
        RUNNER.main()
    assert exc.value.code == 2 and marker.read_text() == "original"


def test_anonymous_mode_requires_explicit_selection(setup, monkeypatch):
    _, output = setup
    monkeypatch.delenv("GITHUB_TOKEN")
    with pytest.raises(SystemExit) as exc:
        RUNNER.main()
    assert exc.value.code == 2 and not output.exists()
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--anonymous"])
    assert RUNNER.main() == 0
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["repositories"][0]["scorecard"]["authentication"] == "anonymous"


def test_repository_failure_does_not_stop_batch(setup, monkeypatch):
    _, output = setup

    def metadata(repo, *_):
        if repo == "acme/demo":
            raise OSError("simulated metadata failure")
        return {"default_branch": "main"}

    monkeypatch.setattr(RUNNER, "metadata", metadata)
    assert RUNNER.main() == 1
    repos = json.loads((output / "manifest.json").read_text())["repositories"]
    assert repos[0]["status"] == "failed" and repos[1]["scorecard"]["status"] == "report_written"


def test_timeout_and_credential_leak(setup, monkeypatch):
    _, output = setup
    monkeypatch.setenv("FAKE_LEAK", "1")
    assert RUNNER.main() == 1
    assert all(
        b"test-credential-never-publish" not in p.read_bytes() for p in output.rglob("*") if p.is_file()
    )
    log = output / "timeout.log"
    code, timed_out = RUNNER.execute([sys.executable, "-c", "import time; time.sleep(60)"], log, log, {}, 1)
    assert timed_out and code != 0


def test_retry_keeps_previous_attempt(setup, monkeypatch):
    _, output = setup
    monkeypatch.setenv("FAKE_RETRY", "1")
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--retries", "1"])
    assert RUNNER.main() == 0
    result = json.loads((output / "manifest.json").read_text())["repositories"][0]["scorecard"]
    assert [attempt["exit_code"] for attempt in result["attempts"]] == [1, 0]
    assert (output / "acme/demo/attempt-1/scorecard.log").exists()


@pytest.mark.parametrize(
    "data", [[], {}, ["../bad"], ["a/.."], ["a/b", "A/B"], ["https://github.com/a/b"], [1]]
)
def test_invalid_repository_inputs(tmp_path, data):
    path = tmp_path / "repos.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        RUNNER.repositories(path)


def test_truncated_export_is_not_written_successfully(tmp_path):
    report = tmp_path / "partial.txt"
    report.write_text("╭─ Metrics ─╮\n╰───────────╯\n")
    assert not RUNNER.report_written("repoauditor", report, "a/b")
