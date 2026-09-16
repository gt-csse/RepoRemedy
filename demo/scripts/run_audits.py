# noqa: CPY001, INP001
"""Run external audit tools; keep this demo utility independent of RepoRemedy."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from typing import NoReturn
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MODULES = ("GitHub", "CommunityStandards", "ScientificSoftware")


def fail(message: str) -> NoReturn:
    """Reject invalid runner input."""
    raise ValueError(message)


def now() -> str:
    """Return a UTC timestamp for provenance."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def repositories(path: Path) -> list[str]:
    """Read a JSON array of unique GitHub OWNER/REPO names."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        fail("Repository input must be a nonempty JSON array")
    for repo in data:
        if (
            not isinstance(repo, str)
            or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9_.-]+", repo)
            or repo.split("/")[1] in {".", ".."}
        ):
            fail("Use GitHub OWNER/REPO names, not URLs or filesystem paths")
    if len({repo.casefold() for repo in data}) != len(data):
        fail("Duplicate repository names are not allowed")
    return data


def metadata(repo: str, token: str, retries: int) -> dict:
    """Resolve the default branch using the same credential as the scans."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "RepoRemedy-demo"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"https://api.github.com/repos/{repo}", headers=headers)
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS GitHub host
                result = json.load(response)
            if not isinstance(result.get("default_branch"), str) or not result["default_branch"]:
                fail("GitHub did not return a default branch")
        except OSError, ValueError:
            if attempt == retries:
                raise
            time.sleep(2**attempt)
        else:
            return result
    fail("Metadata retries exhausted")


def execute(
    command: list[str], stdout: Path, log: Path, env: dict[str, str], timeout: int
) -> tuple[int, bool]:
    """Bound tool execution and terminate its process group on timeout (POSIX)."""
    with ExitStack() as stack:
        output = stack.enter_context(stdout.open("wb"))
        errors = output if stdout == log else stack.enter_context(log.open("ab"))
        with subprocess.Popen(  # noqa: S603 - explicit executable and argument array; no shell
            command, stdout=output, stderr=errors, env=env, start_new_session=True
        ) as process:
            try:
                return process.wait(timeout=timeout), False
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                return process.returncode, True


def report_written(tool: str, report: Path, repo: str) -> bool:
    """Perform basic export checks, not RepoRemedy reader or finding validation."""
    if not report.is_file() or not report.stat().st_size:
        return False
    text = report.read_text(encoding="utf-8")
    if tool == "repoauditor":
        # RepoAuditor exits 255 for findings as well as failures. Require all module footers.
        return len(re.findall(r"^[ │┃]*[╭┌][─━ ]*Metrics[─━ ]*[╮┐][ │┃]*$", text, re.MULTILINE)) == len(
            MODULES
        ) and text.rstrip().endswith(("╯", "┘"))
    scan = json.loads(text)
    return (
        scan["repo"]["name"].removeprefix("github.com/").casefold() == repo.casefold()
        and isinstance(scan["checks"], list)
        and bool(scan["checks"])
    )


def run_tool(repo: str, branch: str, tool: str, args: argparse.Namespace, secret: Path) -> dict:
    """Keep each retry's artifacts and return its execution metadata."""
    token = secret.read_text(encoding="utf-8")
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "GITHUB_AUTH_TOKEN",
            "GITHUB_TOKEN",
            "GH_AUTH_TOKEN",
            "GH_TOKEN",
            "GITHUB_APP_KEY_PATH",
            "GITHUB_APP_ID",
            "GITHUB_APP_INSTALLATION_ID",
        }
    }
    env.update(
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0="credential.helper",
        GIT_CONFIG_VALUE_0="",
        GIT_TERMINAL_PROMPT="0",
        NO_COLOR="1",
    )
    if tool == "scorecard" and token:
        env["GITHUB_AUTH_TOKEN"] = token
    attempts = []
    for number in range(1, args.retries + 2):
        folder = args.output / repo / f"attempt-{number}"
        folder.mkdir(parents=True, exist_ok=True)
        report = folder / ("repoauditor.txt" if tool == "repoauditor" else "scorecard.json")
        log = folder / f"{tool}.log"
        command = [getattr(args, tool)]
        if tool == "repoauditor":
            for module in MODULES:
                command += [
                    "--include",
                    module,
                    f"--{module}-url",
                    f"https://github.com/{repo}",
                    f"--{module}-branch",
                    branch,
                ]
            if token:
                command += ["--GitHub-pat", str(secret)]
            command += ["--output", str(report)]
        else:
            command += [f"--repo=github.com/{repo}", "--format=json", "--show-details"]
        result = {
            "started_at": now(),
            "status": "failed",
            "exit_code": None,
            "timed_out": False,
            "authentication": "token" if token else "anonymous",
            "command": ["<private-token-file>" if arg == str(secret) else arg for arg in command],
            "report": None,
            "log": str(log.relative_to(args.output)),
        }
        try:
            code, timed_out = execute(command, report if tool == "scorecard" else log, log, env, args.timeout)
            result.update(exit_code=code, timed_out=timed_out)
            # Do not retain credentials if an external tool echoes one.
            leaked = [p for p in (report, log) if token and p.exists() and token.encode() in p.read_bytes()]
            if leaked:
                for path in leaked:
                    path.unlink()
                log.write_text(
                    "Output withheld because it contained the supplied credential.\n", encoding="utf-8"
                )
            if report.exists() and report.stat().st_size:
                result.update(
                    report=str(report.relative_to(args.output)),
                    sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
                )
            if (
                not leaked
                and not timed_out
                and code in ({0, 255} if tool == "repoauditor" else {0})
                and report_written(tool, report, repo)
            ):
                result["status"] = "report_written"
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            result["error"] = type(exc).__name__
        result["finished_at"] = now()
        attempts.append(result)
        if result["status"] == "report_written":
            break
        if number <= args.retries:
            time.sleep(2 ** (number - 1))
    return {**attempts[-1], "attempts": attempts, "reader_validation": "not_performed"}


def run_repository(repo: str, args: argparse.Namespace, secret: Path) -> dict:
    """Isolate a repository failure so the rest of the batch can finish."""
    record = {"repository": repo, "url": f"https://github.com/{repo}"}
    try:
        branch = metadata(repo, secret.read_text(encoding="utf-8"), args.retries)["default_branch"]
        record["default_branch"] = branch
        for tool in ("repoauditor", "scorecard"):
            record[tool] = run_tool(repo, branch, tool, args, secret)
    except Exception as exc:
        record.update(status="failed", error=type(exc).__name__)
        if isinstance(exc, HTTPError):
            record["http_status"] = exc.code
    return record


def main() -> int:
    """Parse demo-runner options and write a new batch manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repositories", type=Path, help="JSON array of GitHub OWNER/REPO names")
    parser.add_argument("--output", required=True, type=Path, help="New output directory; must not exist")
    parser.add_argument("--repoauditor", default="RepoAuditor", help="RepoAuditor executable name or path")
    parser.add_argument("--scorecard", default="scorecard", help="Scorecard executable name or path")
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=2)
    parser.add_argument(
        "--retries", type=int, choices=range(4), default=0, help="Retries per failed scan/API request"
    )
    parser.add_argument("--timeout", type=int, default=900, help="Seconds per tool invocation")
    parser.add_argument(
        "--anonymous", action="store_true", help="Run without a GitHub token (limited evidence)"
    )
    args = parser.parse_args()
    token = "" if args.anonymous else os.environ.get("GITHUB_TOKEN", "")
    if os.name != "posix" or args.timeout < 1:
        parser.error("This runner requires Linux/macOS and a positive timeout")
    if not token and not args.anonymous:
        parser.error("Set GITHUB_TOKEN or explicitly select --anonymous")
    try:
        repos = repositories(args.repositories)
        tools = {}
        for tool in ("repoauditor", "scorecard"):
            binary = shutil.which(getattr(args, tool))
            if not binary:
                fail(f"Executable not found: {tool}")
            setattr(args, tool, str(Path(binary).resolve()))
            version = subprocess.check_output(  # noqa: S603 - resolved user-selected executable, no shell
                [binary, "--version"], stderr=subprocess.STDOUT, timeout=30, text=True
            )
            tools[tool] = {
                "executable": getattr(args, tool),
                "version": version.strip().replace(token, "<redacted>") if token else version.strip(),
            }
        args.output = args.output.resolve()
        args.output.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.error(f"Setup failed ({type(exc).__name__}); check input, tool paths, and output directory")
    manifest = {
        "schema_version": 1,
        "generated_at": now(),
        "tools": tools,
        "notes": [
            "Execution provenance only; reader validation is not performed.",
            "Reports capture live state, not an atomic repository snapshot.",
            "Missing evidence is not a confirmed defect. Authentication is never silently downgraded.",
        ],
        "repositories": [],
    }
    with tempfile.TemporaryDirectory(prefix="reporemedy-credentials-") as private:
        secret = Path(private) / "token"
        secret.touch(mode=0o600)
        secret.write_text(token, encoding="utf-8")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            records = list(pool.map(lambda repo: run_repository(repo, args, secret), repos))
        manifest["repositories"] = records
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return int(
        any(
            record.get(tool, {}).get("status") != "report_written"
            for record in records
            for tool in ("repoauditor", "scorecard")
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
