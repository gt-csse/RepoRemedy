**Project:**
[![License](https://img.shields.io/github/license/gt-csse/RepoRemedy?color=dark-green)](https://github.com/gt-csse/RepoRemedy/blob/master/LICENSE)

**Package:**
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/RepoRemedy?color=dark-green)](https://pypi.org/project/RepoRemedy/)
[![PyPI - Version](https://img.shields.io/pypi/v/RepoRemedy?color=dark-green)](https://pypi.org/project/RepoRemedy/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/RepoRemedy)](https://pypistats.org/packages/reporemedy)

**Development:**
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![pytest](https://img.shields.io/badge/pytest-enabled-brightgreen)](https://docs.pytest.org/)
[![CI](https://github.com/gt-csse/RepoRemedy/actions/workflows/CICD.yml/badge.svg)](https://github.com/gt-csse/RepoRemedy/actions/workflows/CICD.yml)
[![Code Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/davidbrownell/2f9d770d13e3a148424f374f74d41f4b/raw/RepoRemedy_code_coverage.json)](https://github.com/gt-csse/RepoRemedy/actions)
[![GitHub commit activity](https://img.shields.io/github/commit-activity/y/gt-csse/RepoRemedy?color=dark-green)](https://github.com/gt-csse/RepoRemedy/commits/main/)

## Contents

- [Overview](#overview)
- [Installation](#installation)
- [Development](#development)
- [Additional Information](#additional-information)
- [License](#license)

## Overview

RepoRemedy aims to lower the barrier to applying software engineering best practices in open-source software (OSS) repositories.

### Who is the target audience?

RepoRemedy is targeted towards two main audiences:

1) **OSS maintainers** who are interested to have an interactive and batched approach to fixing best practices issues in their repos. RepoRemedy allows for interactive exploration of common improvements as well as automated issue and PR generation to apply common "remedies" to a repository.
2) **OSS auditors** who are interested in investigating and potentially applying fixes to multiple repositories. This audience might be an organizational or academic Open Source Program Office (OSPO) or a maintainer who manages a larger number of repositories. RepoRemedy allows for easier management and potentially replication of common fixes across repositories.

### How to use `RepoRemedy`

RepoRemedy has three steps where each step is a separate command. Only the last step makes changes to a GitHub repository.

| Step | Command | What it does | Changes GitHub? |
| --- | --- | --- | --- |
| 1. Inspect | `inspect` | Reads a RepoAuditor or Scorecard report and lists the findings it can fix | No |
| 2. Propose | `propose` | Reads the repository and drafts a concrete issue or PR for each finding | No |
| 3. Publish | `publish` | Creates the issues and PRs you reviewed and approved | Yes, after `--confirm` |

Reports come from RepoAuditor and Scorecard; see [generating input reports](doc/report-inputs.md). Use `--interactive` to run all three steps in one terminal session for a single repository.

> [!NOTE]
> The examples below target the [gt-csse/reporemedy-live-fixture](https://github.com/gt-csse/reporemedy-live-fixture) repository as an example. Replace it with your own repository (`OWNER/REPO`) to run them against your own project.

#### 1. Inspect

`inspect` reads an existing report and writes normalized findings and source provenance as JSON.

```shell
RepoRemedy inspect scorecard_report.json --report-type ossf-scorecard --repo gt-csse/reporemedy-live-fixture
RepoRemedy inspect report.txt --report-type repoauditor --repo https://github.com/gt-csse/reporemedy-live-fixture
```

Use `RepoRemedy inspect --help` for inspection options and `RepoRemedy --version` for the installed version. For GitHub Enterprise, use an HTTPS URL or `HOST/OWNER/REPO`.

> [!NOTE]
> RepoRemedy currently supports RepoAuditor and OpenSSF ScoreCard reports as input. Please see  [report-inputs](doc/report-inputs.md) for more information on how to generate these reports and [demo/reports](demo/reports/) for example reports from sample projects.

#### 2. Propose

`propose` gathers context and creates concrete remedy proposals from an audit report:

```shell
RepoRemedy propose report.json --report-type ossf-scorecard --repo gt-csse/reporemedy-live-fixture > proposals.json
```

`propose` will read the audited commit and branch used for a input report but can also use `main`. Use `--ref main`
or a full commit SHA to select a revision explicitly. It resolves catalog inputs
and renders an issue or an eligible draft PR, including file contents and diffs.
Missing inputs and blocked proposals remain visible. `propose` makes no GitHub changes.

See [repository context](doc/repository-context.md) for authentication, collected
context, maintainer inputs, PR guards and the saved proposal contract.

#### 3. Publish

Publish only reviewed selections, with explicit confirmation:

```shell
RepoRemedy publish proposals.json --repo gt-csse/reporemedy-live-fixture --select security-policy \
  --receipts publication-receipts.json --confirm
```

See [publishing remedies](doc/publishing.md) for permissions, stale-content checks,
duplicate prevention and receipt recovery.

#### Interactive mode

To select and review remedies interactively for one repository, add `--interactive`. The session saves your selections to a plan file:

```shell
RepoRemedy inspect report.txt --report-type repoauditor --repo gt-csse/reporemedy-live-fixture --interactive
RepoRemedy inspect --resume remedy-plan.json
RepoRemedy publish --plan remedy-plan.json
```

`publish --plan` takes the plan file saved by an interactive session whereas `publish proposals.json` takes the output of `propose` run without an interactive session or other flags.

The [interactive workflow](doc/interactive.md) supports bulk selection, input forms, issue/PR previews, save/resume and confirmed publication. Without `--interactive`, `inspect` prints findings as JSON to stdout and writes no file.

#### Several repositories

Generate proposals for several repositories using report-path templates:

```shell
RepoRemedy propose-batch demo/batch.json --output batch-results
```

The [batch workflow](doc/batch.md) uses the same remediation behavior as `propose`,
preserves each repository's bundles and summary, and continues after input failures.
Exit code `3` identifies partial failure; output directories must be new.

## Installation

| Installation Method | Command |
| --- | --- |
| Via [uv](https://github.com/astral-sh/uv) | `uv add RepoRemedy` |
| Via [pip](https://pip.pypa.io/en/stable/) | `pip install RepoRemedy` |

RepoRemedy requires Python 3.14 or later. See the [installation guide](doc/INSTALL.md) for requirements, GitHub token setup, installing from source, upgrading and troubleshooting.

### Verifying Signed Artifacts

Artifacts are signed and verified using [py-minisign](https://github.com/x13a/py-minisign) and the public key in the file `./minisign_key.pub`.

To verify that an artifact is valid, visit [the latest release](https://github.com/gt-csse/RepoRemedy/releases/latest) and download the `.minisign` signature file that corresponds to the artifact, then run the following command, replacing `<filename>` with the name of the artifact to be verified:

```shell
uv run --with py-minisign python -c "import minisign; minisign.PublicKey.from_file('minisign_key.pub').verify_file('<filename>'); print('The file has been verified.')"
```

## Development

Please visit [Contributing](https://github.com/gt-csse/RepoRemedy/blob/main/CONTRIBUTING.md) and [Development](https://github.com/gt-csse/RepoRemedy/blob/main/DEVELOPMENT.md) for information on contributing to this project.

## Additional Information

Additional information can be found at these locations.

| Title | Document | Description |
| --- | --- | --- |
| Code of Conduct | [CODE_OF_CONDUCT.md](https://github.com/gt-csse/RepoRemedy/blob/main/CODE_OF_CONDUCT.md) | Information about the norms, rules, and responsibilities we adhere to when participating in this open source community. |
| Contributing | [CONTRIBUTING.md](https://github.com/gt-csse/RepoRemedy/blob/main/CONTRIBUTING.md) | Information about contributing to this project. |
| Development | [DEVELOPMENT.md](https://github.com/gt-csse/RepoRemedy/blob/main/DEVELOPMENT.md) | Information about development activities involved in making changes to this project. |
| Governance | [GOVERNANCE.md](https://github.com/gt-csse/RepoRemedy/blob/main/GOVERNANCE.md) | Information about how this project is governed. |
| Maintainers | [MAINTAINERS.md](https://github.com/gt-csse/RepoRemedy/blob/main/MAINTAINERS.md) | Information about individuals who maintain this project. |
| Security | [SECURITY.md](https://github.com/gt-csse/RepoRemedy/blob/main/SECURITY.md) | Information about how to privately report security issues associated with this project. |

## License

`RepoRemedy` is licensed under the [MIT](https://choosealicense.com/licenses/MIT/) license.