# noqa: CPY001
"""Load and validate packaged non-LLM remedy definitions."""

import hashlib
import re
from importlib.resources import files
from pathlib import PurePosixPath
from string import Template
import tomllib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from RepoRemedy.context.github import ContextError


class ProposedFile(BaseModel):
    """A repository destination and packaged source file."""

    model_config = ConfigDict(extra="forbid")
    path: str
    template: str
    operation: Literal["create"]


class Route(BaseModel):
    """A declared issue or PR customization route."""

    model_config = ConfigDict(extra="forbid")
    title: str
    body: str
    required_inputs: list[str]
    change_summary: str | None = None
    guards: list[str] = Field(default_factory=list)
    files: list[ProposedFile] = Field(default_factory=list)


class Remedy(BaseModel):
    """One stable remedy, independent of catalog grouping."""

    model_config = ConfigDict(extra="forbid")
    sources: dict[Literal["RA", "OSSF"], list[str]]
    response: str
    issue: Route
    pr: Route | None = None


BODY_TYPES = {
    "issue": {"settings-issue.md", "engineering-issue.md", "decision-issue.md", "documentation-issue.md"},
    "pr": {"create-files-pr.md"},
}


def asset(folder: str, name: str) -> str:
    """Read a packaged body or proposed-file asset, including in installed wheels."""
    if (
        folder not in {"bodies", "files"}
        or PurePosixPath(name).name != name
        or "\\" in name
        or name in {"", ".", ".."}
    ):
        message = "Invalid catalog asset path"
        raise ContextError(message)
    return files("RepoRemedy").joinpath("templates", folder, name).read_text(encoding="utf-8")


def _validate_route(remedy: Remedy, route: Route, kind: str) -> None:
    if route.body not in BODY_TYPES[kind]:
        message = "Unsupported catalog body"
        raise ContextError(message)
    if (
        len(route.required_inputs) != len(set(route.required_inputs))
        or any(not re.fullmatch(r"[a-z][a-z0-9_]*", key) for key in route.required_inputs)
        or (kind == "issue" and (route.files or route.guards or route.change_summary))
    ):
        message = "Invalid route input declarations or issue-only fields"
        raise ContextError(message)
    fixed = {"response"} | ({"change_summary"} if kind == "pr" else set())
    texts = [route.title, asset("bodies", route.body)]
    if kind == "pr" and (
        set(route.guards) != {"confirmed_gap", "target_absent", "no_equivalent_file", "approved_inputs"}
        or not route.files
        or not route.change_summary
    ):
        message = "Incomplete PR route"
        raise ContextError(message)
    for file in route.files:
        path = PurePosixPath(file.path)
        if (
            path.is_absolute()
            or any(p.lower() in {"..", ".git"} for p in path.parts)
            or "\\" in file.path
            or ":" in file.path
        ):
            message = "Unsafe proposed file destination"
            raise ContextError(message)
        texts.append(asset("files", file.template))
    used = set()
    for text in texts:
        template = Template(text)
        if not template.is_valid():
            message = "Invalid catalog placeholder"
            raise ContextError(message)
        used.update(template.get_identifiers())
    if (
        used != set(route.required_inputs) | fixed
        or fixed.intersection(route.required_inputs)
        or not remedy.response
    ):
        message = "Catalog inputs do not match template placeholders"
        raise ContextError(message)


def load_catalog() -> tuple[dict[str, Remedy], str]:
    """Validate catalog contracts and identify all packaged content by one digest."""
    root = files("RepoRemedy").joinpath("templates")
    remedies: dict[str, Remedy] = {}
    sources = set()
    digest = hashlib.sha256()
    for folder in ("catalog", "bodies", "files"):
        for path in sorted(root.joinpath(folder).iterdir(), key=lambda item: item.name):
            if folder == "catalog" and not path.name.endswith(".toml"):
                continue
            raw = path.read_bytes()
            digest.update(f"{folder}/{path.name}\0".encode() + raw + b"\0")
            if folder != "catalog":
                continue
            data = tomllib.loads(raw.decode("utf-8"))
            if data.get("schema_version") != 3:  # noqa: PLR2004 - declared catalog schema
                message = "Unsupported catalog schema"
                raise ContextError(message)
            for identifier, value in data["remedies"].items():
                remedy = Remedy.model_validate(value)
                if (
                    not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identifier)
                    or not remedy.sources
                    or any(
                        not checks or len(checks) != len(set(checks)) for checks in remedy.sources.values()
                    )
                ):
                    message = "Invalid remedy identity or source declarations"
                    raise ContextError(message)
                pairs = {(origin, check) for origin, checks in remedy.sources.items() for check in checks}
                if identifier in remedies or sources.intersection(pairs):
                    message = "Duplicate remedy or check mapping"
                    raise ContextError(message)
                sources.update(pairs)
                _validate_route(remedy, remedy.issue, "issue")
                if remedy.pr:
                    _validate_route(remedy, remedy.pr, "pr")
                remedies[identifier] = remedy
    return remedies, digest.hexdigest()
