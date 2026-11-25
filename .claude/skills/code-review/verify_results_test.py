# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pytest",
#     "typer",
# ]
# ///

"""Tests for verify_results.py.

The repository has no pyproject.toml, so this file carries its own PEP 723 metadata and
is run directly:

    uv run --no-project verify_results_test.py
"""

import json
import sys

from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from verify_results import (  # noqa: E402
    Check,
    CheckRecord,
    Item,
    LoadExpected,
    LoadResults,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _WriteItems(tmp_path: Path, batches: object) -> Path:
    path = tmp_path / "checklist_items.json"
    path.write_text(json.dumps({"batches": batches}), encoding="utf-8")
    return path


def _OneItemList(tmp_path: Path) -> Path:
    return _WriteItems(
        tmp_path,
        [
            {
                "id": "A",
                "category": "Architecture",
                "items": [{"id": "A1", "severity": "high", "text": "Item text."}],
            }
        ],
    )


def _Record(**overrides: object) -> dict:
    record = {
        "id": "A1",
        "verdict": "pass",
        "population_size": 2,
        "evidence": "Examined two files.",
        "_source": "A.json",
    }
    record.update(overrides)
    return record


# ----------------------------------------------------------------------
# LoadExpected
# ----------------------------------------------------------------------
def test_LoadExpectedReturnsReportFields(tmp_path: Path) -> None:
    expected = LoadExpected(_OneItemList(tmp_path))
    assert expected == {"A1": Item("A", "Architecture", "high", "Item text.")}


def test_LoadExpectedRejectsInvalidJson(tmp_path: Path) -> None:
    path = tmp_path / "checklist_items.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(SystemExit, match="not valid JSON"):
        LoadExpected(path)


def test_LoadExpectedRejectsMissingBatches(tmp_path: Path) -> None:
    path = tmp_path / "checklist_items.json"
    path.write_text(json.dumps({"items": []}), encoding="utf-8")

    with pytest.raises(SystemExit, match="expected a 'batches' array"):
        LoadExpected(path)


def test_LoadExpectedRejectsDuplicateItemId(tmp_path: Path) -> None:
    path = _WriteItems(
        tmp_path,
        [
            {
                "id": "A",
                "category": "Architecture",
                "items": [
                    {"id": "A1", "severity": "low", "text": "First."},
                    {"id": "A1", "severity": "low", "text": "Second."},
                ],
            }
        ],
    )

    with pytest.raises(SystemExit, match="duplicate item ID 'A1'"):
        LoadExpected(path)


def test_LoadExpectedRejectsEmptyItemList(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="defines no items"):
        LoadExpected(_WriteItems(tmp_path, []))


def test_LoadExpectedRejectsMissingCategory(tmp_path: Path) -> None:
    path = _WriteItems(
        tmp_path,
        [{"id": "A", "items": [{"id": "A1", "severity": "low", "text": "Item."}]}],
    )

    with pytest.raises(SystemExit, match="has no valid 'category'"):
        LoadExpected(path)


def test_LoadExpectedRejectsUnknownSeverity(tmp_path: Path) -> None:
    path = _WriteItems(
        tmp_path,
        [
            {
                "id": "A",
                "category": "Architecture",
                "items": [{"id": "A1", "severity": "urgent", "text": "Item."}],
            }
        ],
    )

    with pytest.raises(SystemExit, match="'severity' 'urgent' is not one of"):
        LoadExpected(path)


def test_LoadExpectedRejectsMissingSeverity(tmp_path: Path) -> None:
    path = _WriteItems(
        tmp_path,
        [{"id": "A", "category": "Architecture", "items": [{"id": "A1", "text": "Item."}]}],
    )

    with pytest.raises(SystemExit, match="'severity' None is not one of"):
        LoadExpected(path)


def test_LoadExpectedRejectsEmptyText(tmp_path: Path) -> None:
    path = _WriteItems(
        tmp_path,
        [
            {
                "id": "A",
                "category": "Architecture",
                "items": [{"id": "A1", "severity": "low", "text": "   "}],
            }
        ],
    )

    with pytest.raises(SystemExit, match="'text' is missing or empty"):
        LoadExpected(path)


# ----------------------------------------------------------------------
# LoadResults
# ----------------------------------------------------------------------
def test_LoadResultsTagsEachRecordWithItsSourceFile(tmp_path: Path) -> None:
    (tmp_path / "A.json").write_text(json.dumps([{"id": "A1"}]), encoding="utf-8")
    records, errors = LoadResults(tmp_path)

    assert errors == []
    assert records == [{"id": "A1", "_source": "A.json"}]


def test_LoadResultsReportsEmptyDirectory(tmp_path: Path) -> None:
    records, errors = LoadResults(tmp_path)

    assert records == []
    assert len(errors) == 1
    assert "no result files found" in errors[0]


def test_LoadResultsCollectsParseErrorWithoutRaising(tmp_path: Path) -> None:
    (tmp_path / "A.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "B.json").write_text(json.dumps([{"id": "B1"}]), encoding="utf-8")
    records, errors = LoadResults(tmp_path)

    assert len(errors) == 1
    assert "A.json: not valid JSON" in errors[0]
    assert [r["id"] for r in records] == ["B1"]


def test_LoadResultsRejectsNonArrayPayload(tmp_path: Path) -> None:
    (tmp_path / "A.json").write_text(json.dumps({"id": "A1"}), encoding="utf-8")
    records, errors = LoadResults(tmp_path)

    assert records == []
    assert errors == ["A.json: expected a JSON array of records"]


def test_LoadResultsRejectsNonObjectRecord(tmp_path: Path) -> None:
    (tmp_path / "A.json").write_text(json.dumps(["A1"]), encoding="utf-8")
    records, errors = LoadResults(tmp_path)

    assert records == []
    assert errors == ["A.json: contains a non-object record"]


# ----------------------------------------------------------------------
# CheckRecord
# ----------------------------------------------------------------------
def test_CheckRecordAcceptsWellFormedRecord() -> None:
    assert CheckRecord("A1", _Record(), "A.json") == []


def test_CheckRecordAcceptsZeroPopulation() -> None:
    assert CheckRecord("A1", _Record(population_size=0, verdict="n/a"), "A.json") == []


def test_CheckRecordReportsMissingFields() -> None:
    entry = {"id": "A1"}
    problems = CheckRecord("A1", entry, "A.json")

    assert any("missing field(s) verdict, population_size, evidence" in p for p in problems)


def test_CheckRecordRejectsInvalidVerdict() -> None:
    problems = CheckRecord("A1", _Record(verdict="ok"), "A.json")

    assert len(problems) == 1
    assert "verdict 'ok' is not one of" in problems[0]


def test_CheckRecordRejectsBlankEvidence() -> None:
    problems = CheckRecord("A1", _Record(evidence="   "), "A.json")

    assert problems == ["A1: 'evidence' must be a non-empty string (from A.json)"]


def test_CheckRecordRejectsNonStringEvidence() -> None:
    """A null evidence value must not slip past the emptiness check."""

    problems = CheckRecord("A1", _Record(evidence=None), "A.json")

    assert problems == ["A1: 'evidence' must be a non-empty string (from A.json)"]


def test_CheckRecordRejectsBooleanPopulationSize() -> None:
    """bool subclasses int, so `true` must be rejected explicitly."""

    problems = CheckRecord("A1", _Record(population_size=True), "A.json")

    assert problems == ["A1: 'population_size' must be a non-negative integer (from A.json)"]


def test_CheckRecordRejectsNegativePopulationSize() -> None:
    problems = CheckRecord("A1", _Record(population_size=-5), "A.json")

    assert problems == ["A1: 'population_size' must be a non-negative integer (from A.json)"]


def test_CheckRecordRejectsNonIntegerPopulationSize() -> None:
    problems = CheckRecord("A1", _Record(population_size="2"), "A.json")

    assert problems == ["A1: 'population_size' must be a non-negative integer (from A.json)"]


# ----------------------------------------------------------------------
# Check
# ----------------------------------------------------------------------
@pytest.fixture
def expected() -> dict[str, Item]:
    return {"A1": Item("A", "Architecture", "high", "Item text.")}


def test_CheckAcceptsExactlyOneRecordPerItem(expected: dict[str, Item]) -> None:
    assert Check(expected, [_Record()]) == []


def test_CheckReportsUnevaluatedItem(expected: dict[str, Item]) -> None:
    problems = Check(expected, [])

    assert problems == ["A1: NOT EVALUATED -- no result record (owned by batch A)"]


def test_CheckReportsDuplicateRecords(expected: dict[str, Item]) -> None:
    problems = Check(expected, [_Record(), _Record(_source="A2.json")])

    assert problems == ["A1: 2 result records (A.json, A2.json); expected exactly 1"]


def test_CheckReportsNonStringId(expected: dict[str, Item]) -> None:
    problems = Check(expected, [_Record(id=None)])

    assert "A.json: record with missing or non-string 'id'" in problems


def test_CheckReportsUnknownId(expected: dict[str, Item]) -> None:
    problems = Check(expected, [_Record(), _Record(id="Z9", _source="Z.json")])

    assert "Z9: not an item in checklist_items.json (from Z.json)" in problems


def test_CheckFieldChecksUnknownIdRecord(expected: dict[str, Item]) -> None:
    """An unknown ID must not short-circuit field validation for that record."""

    problems = Check(
        expected,
        [_Record(), _Record(id="Z9", verdict="bogus", evidence="", _source="Z.json")],
    )

    assert "Z9: not an item in checklist_items.json (from Z.json)" in problems
    assert any("verdict 'bogus' is not one of" in p for p in problems)
    assert "Z9: 'evidence' must be a non-empty string (from Z.json)" in problems


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
