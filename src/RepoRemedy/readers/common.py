# noqa: CPY001
"""Shared input validation without network access."""

import re

HOST_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"


class ReportError(ValueError):
    """Malformed, ambiguous or unsupported report input."""


def repository_name(value: str) -> str:
    """Normalize GitHub identities, retaining Enterprise hosts for publication."""
    match = re.fullmatch(
        rf"(?:(?:https://)?(?P<host>{HOST_LABEL}(?:\.{HOST_LABEL})*)(?::(?P<port>[0-9]{{1,5}}))?/)?"
        r"(?P<owner>[A-Za-z0-9][A-Za-z0-9-]*)/(?P<repo>[\w.-]+?)(?:\.git)?/?",
        value,
        flags=re.ASCII | re.IGNORECASE,
    )
    if (
        not match
        or match["repo"] in {".", ".."}
        or match["owner"].endswith("-")
        or (match["port"] is not None and not 0 < int(match["port"]) <= 65535)  # noqa: PLR2004
    ):
        message = (
            "Use OWNER/REPO, HOST/OWNER/REPO or a GitHub.com/Enterprise HTTPS repository URL "
            "without credentials, query or fragment"
        )
        raise ReportError(message)
    host = (match["host"] or "github.com").lower()
    if match["port"] is not None and int(match["port"]) != 443:  # noqa: PLR2004 - default HTTPS port
        host = f"{host}:{int(match['port'])}"
    repository = f"{match['owner']}/{match['repo']}".lower()
    # Keep the existing GitHub.com shorthand; other hosts must remain distinct.
    return repository if host == "github.com" else f"{host}/{repository}"
