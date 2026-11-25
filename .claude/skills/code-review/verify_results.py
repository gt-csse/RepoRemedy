# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "typer",
# ]
# ///

"""Reconcile per-item result records against the authoritative item list.

Exits 0 only when every item in checklist_items.json has exactly one well-formed result
record. Any other state -- missing, duplicated, unknown, or malformed -- is
reported by ID and exits non-zero.

Usage:
    uv run --no-project verify_results.py <results-dir> [--items checklist_items.json]
"""

import json
import sys

from pathlib import Path
from typing import Annotated, NamedTuple

import typer


VALID_VERDICTS = {"pass", "fail", "n/a"}
VALID_SEVERITIES = {"critical", "high", "medium", "low"}
REQUIRED_FIELDS = ("id", "verdict", "population_size", "evidence")


class Item(NamedTuple):
    """An item from the authoritative list, with the fields the report renders."""

    batch_id: str
    category: str
    severity: str
    text: str


def LoadExpected(checklist_items_path: Path) -> dict[str, Item]:
    """Map every item ID in the authoritative list to the item's report fields.

    Validates the fields the report depends on, so a malformed list fails here rather
    than part-way through report construction.
    """

    try:
        data = json.loads(checklist_items_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{checklist_items_path.name}: not valid JSON ({exc})")

    if not isinstance(data, dict) or not isinstance(data.get("batches"), list):
        raise SystemExit(f"{checklist_items_path.name}: expected a 'batches' array")

    expected: dict[str, Item] = {}

    for batch_index, batch in enumerate(data["batches"]):
        if not isinstance(batch, dict):
            raise SystemExit(f"batch at index {batch_index} is not an object")

        batch_id = batch.get("id")
        category = batch.get("category")
        items = batch.get("items")

        if not isinstance(batch_id, str) or not batch_id:
            raise SystemExit(f"batch at index {batch_index} has no valid 'id'")

        if not isinstance(category, str) or not category:
            raise SystemExit(f"batch {batch_id} has no valid 'category'")

        if not isinstance(items, list):
            raise SystemExit(f"batch {batch_id} has no 'items' array")

        for item in items:
            if not isinstance(item, dict):
                raise SystemExit(f"batch {batch_id} contains a non-object item")

            item_id = item.get("id")
            severity = item.get("severity")
            text = item.get("text")

            if not isinstance(item_id, str) or not item_id:
                raise SystemExit(f"batch {batch_id} contains an item with no valid 'id'")

            if item_id in expected:
                raise SystemExit(f"checklist_items.json defines duplicate item ID {item_id!r}")

            if severity not in VALID_SEVERITIES:
                raise SystemExit(
                    f"{item_id}: 'severity' {severity!r} is not one of {sorted(VALID_SEVERITIES)}"
                )

            if not isinstance(text, str) or not text.strip():
                raise SystemExit(f"{item_id}: 'text' is missing or empty")

            expected[item_id] = Item(batch_id, category, severity, text)

    if not expected:
        raise SystemExit("checklist_items.json defines no items")

    return expected


def LoadResults(results_dir: Path) -> tuple[list[dict], list[str]]:
    """Read every result record, collecting parse errors rather than raising."""

    records: list[dict] = []
    errors: list[str] = []
    files = sorted(results_dir.glob("*.json"))

    if not files:
        errors.append(f"no result files found in {results_dir}")

    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}: not valid JSON ({exc})")
            continue

        if not isinstance(payload, list):
            errors.append(f"{path.name}: expected a JSON array of records")
            continue

        for entry in payload:
            if not isinstance(entry, dict):
                errors.append(f"{path.name}: contains a non-object record")
                continue

            entry["_source"] = path.name
            records.append(entry)

    return records, errors


def CheckRecord(item_id: str, entry: dict, source: str) -> list[str]:
    """Return one problem string per field-level defect in a single record."""

    problems: list[str] = []

    missing = [f for f in REQUIRED_FIELDS if f not in entry]
    if missing:
        problems.append(f"{item_id}: missing field(s) {', '.join(missing)} (from {source})")

    if entry.get("verdict") not in VALID_VERDICTS:
        problems.append(
            f"{item_id}: verdict {entry.get('verdict')!r} is not one of "
            f"{sorted(VALID_VERDICTS)} (from {source})"
        )

    evidence = entry.get("evidence")
    if "evidence" in entry and (not isinstance(evidence, str) or not evidence.strip()):
        problems.append(f"{item_id}: 'evidence' must be a non-empty string (from {source})")

    # bool is a subclass of int, so it must be excluded explicitly or `true` passes as a count.
    population_size = entry.get("population_size")
    if "population_size" in entry and (
        isinstance(population_size, bool)
        or not isinstance(population_size, int)
        or population_size < 0
    ):
        problems.append(
            f"{item_id}: 'population_size' must be a non-negative integer (from {source})"
        )

    return problems


def Check(expected: dict[str, Item], records: list[dict]) -> list[str]:
    """Return one problem string per reconciliation failure."""

    problems: list[str] = []
    seen: dict[str, list[str]] = {}

    for entry in records:
        source = entry.get("_source", "<unknown>")
        item_id = entry.get("id")

        if not isinstance(item_id, str) or not item_id:
            problems.append(f"{source}: record with missing or non-string 'id'")
            continue

        seen.setdefault(item_id, []).append(source)

        # An unknown ID is still field-checked, so one bad record reports every defect it has.
        if item_id not in expected:
            problems.append(f"{item_id}: not an item in checklist_items.json (from {source})")

        problems += CheckRecord(item_id, entry, source)

    for item_id, item in sorted(expected.items()):
        sources = seen.get(item_id)
        if not sources:
            problems.append(
                f"{item_id}: NOT EVALUATED -- no result record (owned by batch {item.batch_id})"
            )
        elif len(sources) > 1:
            problems.append(
                f"{item_id}: {len(sources)} result records ({', '.join(sources)}); expected exactly 1"
            )

    return problems


app = typer.Typer(
    help=__doc__,
    add_completion=False,
)


@app.command()
def main(
    results_dir: Annotated[
        Path,
        typer.Argument(help="Directory of result record files."),
    ],
    checklist_items: Annotated[
        Path | None,
        typer.Option("--items", help="Path to the authoritative item list."),
    ] = None,
) -> None:
    checklist_items_path = checklist_items or Path(__file__).with_name("checklist_items.json")
    if not checklist_items_path.is_file():
        sys.stderr.write(f"FAIL: item list not found at {checklist_items_path}\n")
        raise typer.Exit(2)

    if not results_dir.is_dir():
        sys.stderr.write(f"FAIL: results directory not found at {results_dir}\n")
        raise typer.Exit(2)

    expected = LoadExpected(checklist_items_path)
    records, errors = LoadResults(results_dir)
    problems = errors + Check(expected, records)

    if problems:
        sys.stdout.write(f"FAIL: {len(problems)} problem(s) reconciling {len(expected)} item(s):\n")

        for problem in problems:
            sys.stdout.write(f"  - {problem}\n")

        raise typer.Exit(1)

    by_id = {r["id"]: r for r in records}
    sys.stdout.write(
        f"OK: all {len(expected)} item(s) have exactly one well-formed result record.\n"
    )

    for item_id in sorted(expected):
        entry = by_id[item_id]
        sys.stdout.write(
            f"  {item_id}: {entry['verdict']} "
            f"(severity {expected[item_id].severity}, population {entry['population_size']})\n"
        )


if __name__ == "__main__":
    app()
