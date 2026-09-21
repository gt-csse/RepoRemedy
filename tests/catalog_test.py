"""Packaged catalog validation and asset boundaries."""

from pathlib import Path
import json
import shutil

import pytest

from RepoRemedy.catalog import ProposedFile, read_asset, load_catalog
from RepoRemedy.context.github import ContextError

ASSETS = Path(__file__).resolve().parents[1] / "src/RepoRemedy/templates"


@pytest.mark.parametrize(
    "folder,name",
    [("other", "README.md"), ("files", "../README.md"), ("files", "x\\README.md"), ("files", "..")],
)
def test_catalog_paths_are_bounded(folder, name):
    with pytest.raises(ContextError):
        read_asset(folder, name)


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("schema_version = 3", "schema"),
        ('body = "documentation-issue.md"', "body"),
        ('guards = ["confirmed_gap", "target_absent", "no_equivalent_file", "approved_inputs"]', "PR route"),
        ('path = "CITATION.cff"', "destination"),
        ('"approved_citation_metadata",', "placeholders"),
    ],
)
def test_invalid_catalog_contracts_fail_explicitly(tmp_path, monkeypatch, mutation, error):
    shutil.copytree(ASSETS, tmp_path / "templates")
    path = tmp_path / "templates/catalog/documentation.toml"
    replacements = {
        "schema": "schema_version = 99",
        "body": 'body = "missing.md"',
        "PR route": "guards = []",
        "destination": 'path = "../outside"',
        "placeholders": "",
    }
    path.write_text(path.read_text().replace(mutation, replacements[error], 1))
    monkeypatch.setattr("RepoRemedy.catalog.files", lambda _: tmp_path)
    with pytest.raises(ContextError, match=error):
        load_catalog()


def test_duplicate_catalog_sources_and_invalid_placeholders(tmp_path, monkeypatch):
    shutil.copytree(ASSETS, tmp_path / "templates")
    monkeypatch.setattr("RepoRemedy.catalog.files", lambda _: tmp_path)
    path = tmp_path / "templates/catalog/extra.toml"
    path.write_text((tmp_path / "templates/catalog/documentation.toml").read_text())
    with pytest.raises(ContextError, match="Duplicate"):
        load_catalog()
    path.unlink()
    (tmp_path / "templates/bodies/documentation-issue.md").write_text("Invalid ${")
    with pytest.raises(ContextError, match="placeholder"):
        load_catalog()


@pytest.mark.parametrize(
    "old,new",
    [
        ('"verification_steps",', '"verification_steps", "verification_steps",'),
        ('sources = { RA = ["Citation"] }', "sources = { RA = [] }"),
        ('path = "CITATION.cff"', 'path = ".GIT/config"'),
    ],
)
def test_ambiguous_or_unsafe_catalog_declarations(tmp_path, monkeypatch, old, new):
    shutil.copytree(ASSETS, tmp_path / "templates")
    path = tmp_path / "templates/catalog/documentation.toml"
    path.write_text(path.read_text().replace(old, new, 1))
    monkeypatch.setattr("RepoRemedy.catalog.files", lambda _: tmp_path)
    with pytest.raises(ContextError):
        load_catalog()


def test_catalog_destinations_remain_typed_and_serialize_as_posix():
    catalog = load_catalog()
    assert len(catalog.remedies) == 68 and len(catalog.sha256) == 64
    route = catalog.remedies["ra-issue-templates"].pr
    assert route is not None
    file = route.files[0]
    assert isinstance(file.path, Path)
    assert json.loads(file.model_dump_json())["path"] == file.path.as_posix()
    assert ProposedFile.model_validate_json(file.model_dump_json()) == file


@pytest.mark.parametrize("path", ["x\\README.md", "C:/README.md"])
def test_destination_syntax_is_checked_before_path_conversion(path):
    with pytest.raises(ValueError, match="Unsafe proposed file destination"):
        ProposedFile(path=path, template="README.md", operation="create")
