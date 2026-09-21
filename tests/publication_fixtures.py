"""Stateful GitHub simulation for publication and retry behavior."""

import json

import httpx

from RepoRemedy.propose import propose_remedies
from remedy_fixtures import make_report
from repository_context_test import FakeGitHub, COMMIT

NEW_TREE = "d" * 40
NEW_COMMIT = "c" * 40


class PublishingGitHub(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.responses[""].update(permissions={"push": True}, has_issues=True)
        self.issues = []
        self.refs = {}
        self.overrides = {}
        self.posts = []

    def __call__(self, request):
        suffix = request.url.path.split("/repos/acme/demo", 1)[1]
        override = self.overrides.get((request.method, suffix))
        if override is not None:
            self.requests.append(request)
            return override(request) if callable(override) else override
        if request.method == "GET":
            if suffix == "/issues":
                self.requests.append(request)
                page = int(request.url.params["page"])
                assert request.url.params["state"] == "all"
                return httpx.Response(200, json=self.issues[(page - 1) * 100 : page * 100])
            if suffix.startswith("/git/ref/heads/"):
                self.requests.append(request)
                sha = self.refs.get(suffix.removeprefix("/git/ref/heads/"))
                return httpx.Response(200, json={"object": {"sha": sha}}) if sha else httpx.Response(404)
            return super().__call__(request)
        self.requests.append(request)
        assert request.method == "POST"
        payload = json.loads(request.content)
        self.posts.append((suffix, payload))
        if suffix == "/git/trees":
            return httpx.Response(201, json={"sha": NEW_TREE})
        if suffix == "/git/commits":
            return httpx.Response(201, json={"sha": NEW_COMMIT})
        if suffix == "/git/refs":
            ref = payload["ref"].removeprefix("refs/heads/")
            if ref in self.refs:
                return httpx.Response(422)
            self.refs[ref] = payload["sha"]
            return httpx.Response(201, json={"ref": payload["ref"], "object": {"sha": payload["sha"]}})
        assert suffix in {"/issues", "/pulls"}
        item = {
            "number": len(self.issues) + 1,
            "title": payload["title"],
            "body": payload["body"],
            "state": "open",
        }
        if suffix == "/pulls":
            item.update(pull_request={}, draft=payload["draft"])
        self.issues.append(item)
        return httpx.Response(201, json=item)

    def bundle(self, check="SecurityPolicy", route="auto"):
        return propose_remedies(
            make_report(check),
            self.snapshot(),
            {"ra-require-approvals": {"approved_value": "3", "reported_expected_value": "3"}},
            approved_inputs={"ra-require-approvals", "ra-issue-templates"},
            route=route,
        )
