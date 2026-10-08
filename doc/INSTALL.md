# Installing RepoRemedy

This guide covers installing RepoRemedy and getting it ready to run. For what the tool does and how to use each command, see the [README](../README.md). To work on RepoRemedy itself, see [DEVELOPMENT.md](../DEVELOPMENT.md).

- [Requirements](#requirements)
- [Install](#install)
- [Verify the installation](#verify-the-installation)
- [Set up a GitHub token](#set-up-a-github-token)
- [Install the report generators (optional)](#install-the-report-generators-optional)
- [Verify signed artifacts (optional)](#verify-signed-artifacts-optional)
- [Install from source](#install-from-source)
- [Upgrade and uninstall](#upgrade-and-uninstall)
- [Troubleshooting](#troubleshooting)

## Requirements

| Requirement | Details |
| --- | --- |
| Operating system | Linux, macOS or Windows |
| Python | **3.14 or later** (`requires-python = ">= 3.14"`). [uv](https://docs.astral.sh/uv/) can download a suitable Python for you. |
| Package manager | [uv](https://docs.astral.sh/uv/) (recommended) or [pip](https://pip.pypa.io/en/stable/) |
| GitHub access | A personal access token for the `propose` and `publish` commands. See [Set up a GitHub token](#set-up-a-github-token). |

RepoRemedy installs its own Python dependencies (`httpx`, `pydantic`, `textual` and `typer`).

## Install

### Option 1: uv (recommended)

Install [uv](https://docs.astral.sh/uv/) if you do not already have it:

```shell
# macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then pick one of these:

| Goal | Command |
| --- | --- |
| Install `RepoRemedy` as a standalone command-line tool | `uv tool install RepoRemedy --python 3.14` |
| Add RepoRemedy to an existing uv project | `uv add RepoRemedy` |
| Run once without installing | `uvx RepoRemedy --version` |

If you add RepoRemedy to a project with `uv add`, prefix commands with `uv run`, for example `uv run RepoRemedy --version`.

### Option 2: pip

Make sure `python --version` reports 3.14 or later. A virtual environment is recommended:

```shell
python -m venv .venv

# macOS and Linux
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install RepoRemedy
```

## Verify the installation

```shell
RepoRemedy --version
RepoRemedy --help
```

If the command is not found, see [Troubleshooting](#troubleshooting). You can also run the package as a module with `python -m RepoRemedy --help`.

## Set up a GitHub token

`inspect` works offline on a saved report. The other commands talk to GitHub:

| Command | Token needed? | Access required |
| --- | --- | --- |
| `inspect` | No | None |
| `propose` | Optional for public repositories, recommended to avoid rate limits | Read access to the repository |
| `publish` | **Yes** | Issue write access to create issues. Contents and pull request write access, plus write access to a branch in the target repository, to create draft PRs. Forks are not supported. |

RepoRemedy reads the token from the `REPOREMEDY_TOKEN` environment variable by default:

```shell
# macOS and Linux
export REPOREMEDY_TOKEN=<your-token>

# Windows (PowerShell)
$env:REPOREMEDY_TOKEN = "<your-token>"
```

To use a different variable, for example for GitHub Enterprise, name it with `--token-env`:

```shell
RepoRemedy propose report.txt --report-type repoauditor \
  --repo https://github.example.com/OWNER/REPO --token-env ENTERPRISE_TOKEN > proposals.json
```

Keep tokens out of your repositories, shell history and shared files. RepoRemedy does not store tokens in receipts or saved proposals. See [repository context](repository-context.md) and [publishing remedies](publishing.md) for details.

> [!WARNING]
> `publish --confirm` makes real changes on GitHub (issues, branches and draft PRs). Try the workflow against a test repository such as [gt-csse/reporemedy-live-fixture](https://github.com/gt-csse/reporemedy-live-fixture), or your own sandbox repository, before pointing it at a real project.

## Install the report generators (optional)

RepoRemedy does not generate audit reports itself. It reads reports from these tools:

| Tool | Quick install | Notes |
| --- | --- | --- |
| [RepoAuditor](https://github.com/gt-csse/RepoAuditor) | `uvx RepoAuditor --version`, or `uv add repoauditor` / `pip install repoauditor` | Requires Python 3.10+ and a GitHub PAT saved in a file |
| [OpenSSF Scorecard](https://github.com/ossf/scorecard) | `brew install scorecard`, a [release binary](https://github.com/ossf/scorecard/releases/latest), or `docker pull ghcr.io/ossf/scorecard:latest` | RepoRemedy reads Scorecard **v5** output only. On Windows, use Docker or WSL. |

Full instructions for creating tokens and running each tool are in [Generating Input Reports](report-inputs.md). Example reports are in [demo/reports](../demo/reports/), so you can try RepoRemedy without installing either tool.

## Verify signed artifacts (optional)

Release artifacts are signed with [py-minisign](https://github.com/x13a/py-minisign). The public key is [minisign_key.pub](../minisign_key.pub).

1. Download the artifact and its matching `.minisign` signature file from the [latest release](https://github.com/gt-csse/RepoRemedy/releases/latest), into the same directory.
2. Download `minisign_key.pub` from this repository into that directory.
3. Run, replacing `<filename>` with the artifact name:

```shell
uv run --with py-minisign python -c "import minisign; minisign.PublicKey.from_file('minisign_key.pub').verify_file('<filename>'); print('The file has been verified.')"
```

## Install from source

Use this to run the latest unreleased code or to contribute. You need [git](https://git-scm.com/) and [uv](https://docs.astral.sh/uv/).

```shell
git clone https://github.com/gt-csse/RepoRemedy
cd RepoRemedy
uv sync
uv run RepoRemedy --version
```

`uv sync` creates a `.venv` with the dependencies, including the development tools, and uses the Python version pinned in `.python-version`. To install the checkout as a tool instead, run `uv tool install .`.

For pre-commit hooks, linting, type checking and tests, see [DEVELOPMENT.md](../DEVELOPMENT.md).

## Upgrade and uninstall

| Method | Upgrade | Uninstall |
| --- | --- | --- |
| `uv tool` | `uv tool upgrade RepoRemedy` | `uv tool uninstall RepoRemedy` |
| `uv add` | `uv add --upgrade-package RepoRemedy RepoRemedy` | `uv remove RepoRemedy` |
| `pip` | `pip install --upgrade RepoRemedy` | `pip uninstall RepoRemedy` |

## Troubleshooting

| Problem | Likely cause and fix |
| --- | --- |
| `No solution found` / `requires a different Python` | Your Python is older than 3.14. Use `uv tool install RepoRemedy --python 3.14` or install Python 3.14. |
| `RepoRemedy: command not found` | The install location is not on your `PATH`. For `uv tool`, run `uv tool update-shell` and restart the terminal. For `pip`, activate the virtual environment. As a workaround, use `uv run RepoRemedy` or `python -m RepoRemedy`. |
| GitHub rate-limit or permission errors from `propose` or `publish` | Set `REPOREMEDY_TOKEN` (or pass `--token-env`) to a token with the access listed in [Set up a GitHub token](#set-up-a-github-token). |
| `inspect` rejects a report | Reports must be complete, unedited, and cover one repository and branch. See [Generating Input Reports](report-inputs.md). |
| PowerShell blocks the activation script | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use `uv` instead of a manual virtual environment. |

Still stuck? [Open an issue](https://github.com/gt-csse/RepoRemedy/issues) using the bug report template, and include the output of `RepoRemedy --version` and `python --version`. Report security problems privately as described in [SECURITY.md](../SECURITY.md).
