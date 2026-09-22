"""Shared proposal workflow rejects oversized inputs before collection."""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from RepoRemedy.context.github import ContextError
from RepoRemedy.models import ReportType
from RepoRemedy.workflow import propose_repository


@pytest.mark.parametrize("grows_after_size_check", [False, True])
def test_input_size_checked_before_read_with_growth_guard(
    tmp_path, monkeypatch, track_file_reads, grows_after_size_check
):
    inputs = tmp_path / "inputs.json"
    with inputs.open("wb") as stream:
        stream.truncate(1024 * 1024 + 1)
    tracked = track_file_reads(inputs)
    if grows_after_size_check:
        monkeypatch.setattr("RepoRemedy.workflow.os.fstat", lambda fd: SimpleNamespace(st_size=0))

    def unexpected(*args, **kwargs):
        pytest.fail("Oversized inputs must fail before context collection")

    monkeypatch.setattr("RepoRemedy.workflow.collect_context", unexpected)
    report = Path(__file__).parent / "fixtures/repoauditor.txt"
    with httpx.Client() as client, pytest.raises(ContextError, match="size limit"):
        propose_repository(report, ReportType.REPOAUDITOR, "acme/demo", client, inputs=inputs)
    if grows_after_size_check:
        tracked.read.assert_called_once_with(1024 * 1024 + 1)
    else:
        tracked.read.assert_not_called()
