"""Bounded, host-specific publication requests and duplicate scans."""

import httpx
import pytest

from RepoRemedy.publication.github import GitHubPublisher
from RepoRemedy.publication.receipts import PublicationError
from publication_fixtures import PublishingGitHub


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://other.example/"}),
        httpx.Response(403, json={"message": "PRIVATE"}),
        httpx.Response(201, content=b"bad-json"),
        httpx.Response(201, json=[]),
    ],
)
def test_post_rejects_errors_redirects_and_malformed_responses(response):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "github.example" and request.url.port == 8443
        assert request.url.path == "/api/v3/repos/acme/demo/issues"
        assert request.headers["Authorization"] == "Bearer PRIVATE"
        return response

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        publisher = GitHubPublisher("github.example:8443/acme/demo", client, "PRIVATE")
        with pytest.raises(PublicationError) as exc:
            publisher.post("/issues", {"title": "test"})
        assert "PRIVATE" not in str(exc.value)
    assert len(requests) == 1


def test_post_size_limit_and_read_object_shape(monkeypatch):
    monkeypatch.setattr("RepoRemedy.publication.github.MAX_RESPONSE_BYTES", 3)
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(201, json={"number": 1}))
    ) as client:
        with pytest.raises(PublicationError, match="size limit"):
            GitHubPublisher("acme/demo", client).post("/issues", {})
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))) as client:
        with pytest.raises(PublicationError, match="publication state"):
            GitHubPublisher("acme/demo", client).read_object()


@pytest.mark.parametrize("number", [None, True, -1, 0, "1"])
def test_published_target_requires_positive_integer(number):
    with httpx.Client() as client, pytest.raises(PublicationError, match="number"):
        GitHubPublisher("acme/demo", client).identify_target({"number": number}, "issue")


@pytest.mark.parametrize("data", [None, {}, [False], [{"title": False}], [{"title": "t", "body": 12}]])
def test_inaccessible_or_malformed_duplicate_results_block_creation(data):
    api = PublishingGitHub()
    proposal = api.bundle().proposals[0]
    api.overrides[("GET", "/issues")] = httpx.Response(403 if data is None else 200, json=data)
    with httpx.Client(transport=httpx.MockTransport(api)) as client, pytest.raises(PublicationError):
        GitHubPublisher("acme/demo", client).find_duplicate(proposal, "marker")


def test_duplicate_scan_checks_all_pages_and_refuses_multiple_matches(monkeypatch):
    api = PublishingGitHub()
    proposal = api.bundle().proposals[0]
    api.issues = [{"number": i + 1, "title": "unrelated", "body": None} for i in range(100)]
    api.issues.append({"number": 101, "title": "found", "body": "marker"})
    with httpx.Client(transport=httpx.MockTransport(api)) as client:
        publisher = GitHubPublisher("acme/demo", client)
        found = publisher.find_duplicate(proposal, "marker")
        assert found is not None and found.number == 101
        api.issues.append({"number": 102, "title": "another", "body": "marker"})
        with pytest.raises(PublicationError, match="Multiple"):
            publisher.find_duplicate(proposal, "marker")
        monkeypatch.setattr("RepoRemedy.publication.github.MAX_PAGES", 1)
        with pytest.raises(PublicationError, match="pagination limit"):
            publisher.find_duplicate(proposal, "marker")
