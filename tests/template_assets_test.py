"""Validate the proposed template data independently of a future renderer."""

from pathlib import Path
import re
from string import Template
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "RepoRemedy" / "templates"
BODIES = ASSETS / "bodies"
FILES = ASSETS / "files"
BODY_TYPES = {
    "issue": {"settings-issue.md", "engineering-issue.md", "decision-issue.md", "documentation-issue.md"},
    "pr": {"create-files-pr.md"},
}
CATALOGS = sorted((ASSETS / "catalog").glob("*.toml"))


def read_catalog(path):
    return tomllib.loads(path.read_text(encoding="utf-8"))


REMEDIES = [
    (catalog, remedy_id, data)
    for catalog in CATALOGS
    for remedy_id, data in read_catalog(catalog)["remedies"].items()
]


def safe_path(base, value):
    path = Path(value)
    assert value and not path.is_absolute()
    assert ".." not in path.parts and "\\" not in value
    assert not any(part.lower() == ".git" for part in path.parts)
    assert "${" not in value and ":" not in value
    resolved = (base / path).resolve()
    assert resolved.is_relative_to(base.resolve())
    return resolved


@pytest.mark.parametrize("catalog,remedy_id,data", REMEDIES, ids=[r[1] for r in REMEDIES])
def test_template_contract(catalog, remedy_id, data):
    assert set(data) <= {"sources", "response", "issue", "pr"}
    assert isinstance(data["response"], str) and data["response"].strip()
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", remedy_id)
    assert data["sources"] and set(data["sources"]) <= {"RA", "OSSF"}
    for keys in data["sources"].values():
        assert keys and len(keys) == len(set(keys))
        assert all(isinstance(key, str) and key for key in keys)
    assert "issue" in data
    for name in ("issue", "pr"):
        if name not in data:
            continue
        route = data[name]
        allowed = {"title", "body", "required_inputs"}
        fixed = {"response": data["response"]}
        if name == "pr":
            allowed |= {"guards", "files", "change_summary"}
            assert isinstance(route["change_summary"], str) and route["change_summary"].strip()
            fixed["change_summary"] = route["change_summary"]
        assert set(route) == allowed
        assert route["body"] in BODY_TYPES[name]
        body = safe_path(BODIES, route["body"])
        texts = [route["title"], body.read_text(encoding="utf-8")]
        if name == "pr":
            assert set(route["guards"]) == {
                "confirmed_gap",
                "target_absent",
                "no_equivalent_file",
                "approved_inputs",
            }
            assert route["files"]
            targets = set()
            for entry in route["files"]:
                assert set(entry) == {"path", "template", "operation"}
                assert entry["operation"] == "create"
                target = safe_path(ROOT, entry["path"])
                assert target not in targets
                targets.add(target)
                source = safe_path(FILES, entry["template"])
                texts.append(source.read_text(encoding="utf-8"))
        required = route["required_inputs"]
        assert len(required) == len(set(required))
        assert all(re.fullmatch(r"[a-z][a-z0-9_]*", key) for key in required)
        used = set()
        for text in texts:
            assert text.strip()
            template = Template(text)
            assert template.is_valid()
            used.update(template.get_identifiers())
        assert not set(required) & fixed.keys()
        assert used == set(required) | fixed.keys()
        # Supplied content is inserted literally, without recursively resolving it.
        values = {key: "literal ${unresolved}" for key in required} | fixed
        for text in texts:
            rendered = Template(text).substitute(values)
            assert rendered
            if set(Template(text).get_identifiers()) & set(required):
                assert "literal ${unresolved}" in rendered
        # Fixed guidance is also data, even when it contains placeholder-like text.
        literal_fixed = {key: "guidance ${repository}" for key in fixed}
        assert "guidance ${repository}" in Template(body.read_text()).substitute(values | literal_fixed)


def test_shared_bodies_are_complete_and_used():
    expected = set().union(*BODY_TYPES.values())
    assert {p.name for p in BODIES.iterdir() if p.is_file()} == expected
    used = {data[name]["body"] for _, _, data in REMEDIES for name in ("issue", "pr") if name in data}
    assert used == expected


def test_every_catalog_row_links_to_matching_sources():
    assert REMEDIES, "Template collection must not be empty"
    declared = {}
    for catalog, remedy_id, data in REMEDIES:
        for origin, keys in data["sources"].items():
            for key in keys:
                pair = (origin, key)
                assert pair not in declared, f"Duplicate source mapping: {pair}"
                declared[pair] = (catalog.resolve(), remedy_id)
    linked = {}
    for line in (ROOT / "doc" / "catalog.md").read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith(("| issue", "| ---")):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        assert len(cells) == 4
        matches = re.findall(r"\[Template: ([a-z0-9-]+)\]\(([^)]+)\)", cells[2])
        assert len(matches) == 1
        remedy_id, link = matches[0]
        path = (ROOT / "doc" / link).resolve()
        assert path.is_relative_to(ASSETS.resolve()) and path.is_file()
        keys = re.findall(r"`([^`]+)`", cells[0])
        assert keys
        for key in keys:
            pair = (cells[3], key)
            assert pair not in linked
            linked[pair] = (path, remedy_id)
    assert linked == declared, "Catalog links and template mappings must agree exactly"


def test_topic_catalogs_and_assets_are_complete():
    assert {p.name for p in ASSETS.iterdir()} == {"catalog", "bodies", "files"}
    assert {p.name for p in (ASSETS / "catalog").iterdir()} == {
        "README.md",
        "documentation.toml",
        "repository-settings.toml",
        "branch-protection.toml",
        "engineering.toml",
        "maintainer-decisions.toml",
    }
    ids = [remedy_id for _, remedy_id, _ in REMEDIES]
    assert ids and len(ids) == len(set(ids)), "Remedy IDs must be unique across topics"
    for catalog in CATALOGS:
        data = read_catalog(catalog)
        assert set(data) == {"schema_version", "remedies"}
        assert data["schema_version"] == 3 and data["remedies"]
    referenced = {
        safe_path(FILES, entry["template"])
        for _, _, data in REMEDIES
        for entry in data.get("pr", {}).get("files", [])
    }
    assert referenced == {p.resolve() for p in FILES.iterdir() if p.is_file()}
