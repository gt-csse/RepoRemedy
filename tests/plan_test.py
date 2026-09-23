"""Saved plans retain review state without weakening publisher validation."""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from publication_fixtures import PublishingGitHub
from remedy_fixtures import make_report
from RepoRemedy.context.github import ContextError
from RepoRemedy.plan import MAX_PLAN_BYTES, RemedyPlan, load_plan, save_plan
from RepoRemedy.publication.publish import publish_remedies


def make_plan():
    api = PublishingGitHub()
    bundle = api.bundle()
    plan = RemedyPlan(report=bundle.report, bundle=bundle)
    return plan, api


def approve_plan(plan):
    plan.set_selected("security-policy", selected=True)
    plan.approve("security-policy")


def test_save_resume_publish_and_repeat(tmp_path):
    plan, api = make_plan()
    approve_plan(plan)
    path = tmp_path / "plan.json"
    save_plan(plan, path)
    loaded = load_plan(path)
    assert loaded == plan and loaded.is_reviewed("security-policy")
    receipts = loaded.get_receipt_path(path)
    observed = []
    with httpx.Client(transport=httpx.MockTransport(api)) as client:
        for expected in ["created", "existing"]:
            result = publish_remedies(
                loaded.validate_publication(),
                loaded.selected,
                loaded.report.repository,
                receipts,
                client,
                token="test",
                confirmed=True,
                on_published=observed.append,
            )
            assert result.receipts["security-policy"].status == expected
    assert len(api.posts) == 1
    assert [r.status for r in observed] == ["created", "existing"]


def test_input_approval_and_content_review_are_separate(tmp_path):
    plan, api = make_plan()
    with httpx.Client(transport=httpx.MockTransport(api)) as client:
        plan.collect(client)
    plan.set_selected("security-policy", selected=True)
    proposal = plan.get_proposal("security-policy")
    assert proposal.route == "pr" and proposal.status != "ready"
    with pytest.raises(ContextError):
        plan.approve("security-policy")
    values = plan.get_editable_inputs("security-policy", "pr")
    values.update(security_reporting_instructions="Use the private form", supported_versions="1.x")
    plan.update_inputs("security-policy", "pr", values)
    assert plan.get_proposal("security-policy").status == "ready"
    assert not plan.is_reviewed("security-policy")
    plan.approve("security-policy")
    assert plan.validate_publication()
    plan.update_inputs("security-policy", "pr", values | {"supported_versions": "2.x"})
    assert not plan.is_reviewed("security-policy")
    with pytest.raises(ContextError, match="Review"):
        plan.validate_publication()
    plan.approve("security-policy")
    plan.set_selected("security-policy", selected=False)
    assert plan.selected == [] and plan.reviewed == {}


@pytest.mark.parametrize("mutation", ["content", "base", "context", "catalog", "evidence"])
def test_saved_review_cannot_authorize_changed_content(mutation):
    plan, _ = make_plan()
    approve_plan(plan)
    if mutation == "content":
        plan.bundle.proposals[0].content.body += "Changed"
    elif mutation == "base":
        plan.bundle.base_commit = "9" * 40
    elif mutation == "context":
        plan.bundle.context_sha256 = "0" * 64
    elif mutation == "catalog":
        plan.bundle.catalog_sha256 = "0" * 64
    else:
        plan.bundle.proposals[0].findings[0].evidence += "Changed"
    with pytest.raises(ContextError):
        plan.validate_publication()


def test_unsupported_and_duplicate_ids_are_not_selectable():
    plan, _ = make_plan()
    plan.bundle.proposals.append(plan.bundle.proposals[0].model_copy(deep=True))
    assert not plan.get_selectable_ids()
    with pytest.raises(ContextError, match="exactly one"):
        plan.get_proposal("security-policy")
    with pytest.raises(ContextError):
        plan.set_selected("security-policy", selected=True)
    empty = RemedyPlan(report=make_report("UnknownCheck"))
    assert empty.get_proposals() == []
    with pytest.raises(ContextError):
        empty.approve("security-policy")


@pytest.mark.parametrize("change", ["duplicate", "review", "report", "token"])
def test_invalid_plan_schema(change):
    plan, _ = make_plan()
    raw = plan.model_dump()
    if change == "duplicate":
        raw["selected"] = ["security-policy"] * 2
    elif change == "review":
        raw["reviewed"] = {"security-policy": "anything"}
    elif change == "report":
        raw["report"]["repository"] = "other/repo"
    else:
        raw["token_env"] = "bad-name"
    with pytest.raises(ValidationError):
        RemedyPlan.model_validate(raw)


def test_inputs_are_transactional_and_route_is_explicit():
    plan, _ = make_plan()
    before = plan.model_dump_json()
    for values in [{"evidence": "invented"}, {"supported_versions": " "}]:
        with pytest.raises(ContextError):
            plan.update_inputs("security-policy", "pr", values)
        assert plan.model_dump_json() == before
    plan.update_inputs("security-policy", "issue", {})
    assert plan.get_proposal("security-policy").route == "issue"
    api = PublishingGitHub()
    bundle = api.bundle("RequireApprovals")
    issue = RemedyPlan(report=bundle.report, bundle=bundle)
    with pytest.raises(ContextError, match="does not support"):
        issue.get_editable_inputs("ra-require-approvals", "pr")


@pytest.mark.parametrize("grows", [False, True])
def test_plan_size_precedes_allocation(tmp_path, monkeypatch, track_file_reads, grows):
    path = tmp_path / "large.json"
    with path.open("wb") as stream:
        stream.truncate(MAX_PLAN_BYTES + 1)
    tracked = track_file_reads(path)
    if grows:
        monkeypatch.setattr("RepoRemedy.plan.os.fstat", lambda fd: SimpleNamespace(st_size=0))
    with pytest.raises(ContextError, match="size limit"):
        load_plan(path)
    if grows:
        tracked.read.assert_called_once_with(MAX_PLAN_BYTES + 1)
    else:
        tracked.read.assert_not_called()


def test_save_failure_preserves_previous_plan_and_cleans_temporary(tmp_path, monkeypatch):
    plan, _ = make_plan()
    path = tmp_path / "plan.json"
    save_plan(plan, path)
    before = path.read_bytes()

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        save_plan(plan, path)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_plan_and_receipts_cannot_overwrite_source(tmp_path, monkeypatch):
    plan, _ = make_plan()
    plan.report.source.path = tmp_path / "audit.txt"
    with pytest.raises(ContextError):
        save_plan(plan, plan.report.source.path)
    path = tmp_path / "plan.json"
    plan.receipts = path
    with pytest.raises(ContextError):
        save_plan(plan, path)
    plan.receipts = plan.report.source.path
    with pytest.raises(ContextError):
        plan.get_receipt_path(path)
    plan.receipts = Path("receipts.json")
    monkeypatch.setattr("RepoRemedy.plan.MAX_PLAN_BYTES", 10)
    with pytest.raises(ContextError, match="size limit"):
        save_plan(plan, path)
