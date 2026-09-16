# noqa: CPY001
"""Read intact RepoAuditor Rich panels, retaining source line locations."""

import re

from RepoRemedy.models import Issue, Report, Source
from RepoRemedy.readers.common import fail

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TOP = re.compile(r"^[ │┃]*([╭┌])[─━ ]*\[")
HEADER = re.compile(r"\[(Success|Warning|Error|DoesNotApply)\]\s+([A-Za-z][A-Za-z0-9_]*)[─━ ]*[╮┐][ │┃]*$")
METRICS = re.compile(r"^[ │┃]*([╭┌])[─━ ]*Metrics\b")
INCOMPLETE = re.compile(r"^(?:WARNING|ERROR):\s+Incomplete\s+data\s+was\s+encountered\.$", re.MULTILINE)


def _issue(key: str, status: str, evidence: str, location: str) -> Issue:
    """Normalize unavailable evidence without losing the export's original status."""
    if not evidence:
        fail("RepoAuditor finding has no evidence")
    normalized_status = "warning" if status == "Warning" else "error"
    if INCOMPLETE.search(evidence):
        normalized_status = "unavailable"
    return Issue(
        origin="RA",
        check=key,
        status=normalized_status,
        original_status=status,
        evidence=evidence,
        location=location,
    )


def _validate_metrics(evidence: str, observed: dict[str, int]) -> None:
    """Check module totals; non-verbose exports may omit successful/skipped panels."""
    for label, status in (
        ("Successful", "Success"),
        ("Warnings", "Warning"),
        ("Errors", "Error"),
        ("Skipped", "DoesNotApply"),
    ):
        values = re.findall(rf"^{label}:\s+(\d+)\s+\(\d+(?:\.\d+)?%\)$", evidence, re.MULTILINE)
        if len(values) != 1:
            fail("Incomplete or malformed RepoAuditor Metrics panel")
        count = int(values[0])
        actual = observed.get(status, 0)
        if count < actual or (status in {"Warning", "Error"} and count != actual):
            fail("RepoAuditor Metrics do not match the saved check panels")


def _validate_clean_summary(text: str) -> None:
    """Accept legacy plain summaries only when no warning/error panels are expected."""
    counts = [re.findall(rf"{name}:\s+(\d+)\s+\(", text) for name in ("Warnings", "Errors")]
    if "Metrics" not in text or "Successful:" not in text or not all(c and set(c) == {"0"} for c in counts):
        fail("Unrecognized RepoAuditor export; supply intact saved report panels")


def read_repoauditor(text: str, repository: str, source: Source) -> Report:
    """Reject truncated or ambiguous panels; clean summaries may have no issues."""
    lines = ANSI.sub("", text).splitlines()
    issues = []
    seen = set()
    observed: dict[str, int] = {}
    metrics_count = 0
    active: tuple[int, int, str, str] | None = None
    for index, line in enumerate(lines):
        top = TOP.search(line)
        metrics = METRICS.search(line)
        if active:
            start, depth, status, key = active
            if (
                line[:depth] != lines[start][:depth]
                or len(line) <= depth
                or line[depth] not in "│┃╰└"
                or not line.rstrip().endswith(("│", "┃", "╯", "┘"))
            ):
                fail("Truncated or malformed RepoAuditor panel")
            if line[depth] in "╰└":
                if not re.fullmatch(r"[╰└][─━]+[╯┘][ │┃]*", line[depth:]):
                    fail("Malformed RepoAuditor closing border")
                evidence = "\n".join(row.strip(" │┃") for row in lines[start + 1 : index]).strip()
                if status == "Metrics":
                    _validate_metrics(evidence, observed)
                    observed.clear()
                    metrics_count += 1
                else:
                    observed[status] = observed.get(status, 0) + 1
                if status in {"Warning", "Error"}:
                    issues.append(_issue(key, status, evidence, f"lines:{start + 1}-{index + 1}"))
                active = None
        elif metrics:
            if not re.fullmatch(r"[─━ ]*[╮┐][ │┃]*", line[metrics.end() :]):
                fail("Malformed RepoAuditor Metrics panel header")
            active = (index, metrics.start(1), "Metrics", "")
        elif top:
            header = HEADER.search(line, top.start())
            if not header:
                fail("Unsupported or incomplete RepoAuditor panel header")
            status, key = header.groups()
            if key in seen:
                fail("Repeated RepoAuditor check is ambiguous; select one repository/branch report")
            seen.add(key)
            active = (index, top.start(1), status, key)
    if active:
        fail("Truncated RepoAuditor panel")
    if not seen and not metrics_count:
        _validate_clean_summary("\n".join(lines))
    return Report(
        repository=repository,
        source=source,
        issues=issues,
        notices=[
            "Repository identity is supplied by the caller; text exports do not verify it.",
            (
                "Report completeness is unverified: saved exports do not declare all expected modules. "
                f"Validated {metrics_count} module Metrics panel(s); missing modules or trailing results "
                "cannot be ruled out."
            ),
        ],
    )
