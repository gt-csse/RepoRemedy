# noqa: CPY001
"""Shared input validation without network access."""

import re
from typing import NoReturn


class ReportError(ValueError):
    """Malformed, ambiguous or unsupported report input."""


def fail(message: str) -> NoReturn:
    """Reject input with a user-facing explanation."""
    raise ReportError(message)


def repository_name(value: str) -> str:
    """Normalize an owner/name or unambiguous GitHub repository URL."""
    match = re.fullmatch(
        r"(?:https://github\.com/|github\.com/)?([A-Za-z0-9][A-Za-z0-9-]*)/([\w.-]+?)(?:\.git)?/?",
        value,
        flags=re.ASCII | re.IGNORECASE,
    )
    if not match or match[2] in {".", ".."} or match[1].endswith("-"):
        fail("Repository must be OWNER/REPO or a GitHub repository URL without query or fragment")
    return f"{match[1]}/{match[2]}".lower()
