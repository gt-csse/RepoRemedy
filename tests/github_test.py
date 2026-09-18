"""Tests for the bounded GitHub reader in context/github.py."""

import httpx

from RepoRemedy.context.github import GitHubReader


def test_api_limits_errors_and_redirects(monkeypatch):
    responses = [
        httpx.Response(302, headers={"Location": "https://evil.example"}),
        httpx.Response(200, content=b"bad json"),
        httpx.Response(200, content=b"[]" * 20),
    ]
    monkeypatch.setattr("RepoRemedy.context.github.MAX_RESPONSE_BYTES", 10)
    for response in responses:
        seen = []

        def transport(request):
            seen.append(request)
            return response

        with httpx.Client(transport=httpx.MockTransport(transport), follow_redirects=True) as client:
            result = GitHubReader("acme/demo", client, "TOKEN").read()
        assert result.status == "unavailable" and len(seen) == 1

    def timeout(request):
        raise httpx.ReadTimeout("PRIVATE", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        assert "PRIVATE" not in GitHubReader("acme/demo", client).read().model_dump_json()


def test_pagination_partial_and_limit(monkeypatch):
    monkeypatch.setattr("RepoRemedy.context.github.MAX_PAGES", 2)
    for mode in ("limit", "partial", "malformed"):

        def transport(request):
            if mode == "partial" and request.url.params["page"] == "2":
                return httpx.Response(403)
            return httpx.Response(200, json={} if mode == "malformed" else [1] * 100)

        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            result = GitHubReader("acme/demo", client).read_pages("/hooks")
        assert result.status == ("unavailable" if mode == "malformed" else "partial")
        assert isinstance(result.value, list)
        assert len(result.value) == (0 if mode == "malformed" else 100 if mode == "partial" else 200)
