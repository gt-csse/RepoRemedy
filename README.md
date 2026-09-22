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

<!-- Content above this delimiter will be copied to the generated README.md file. DO NOT REMOVE THIS COMMENT, as it will cause regeneration to fail. -->

## Contents
- [Overview](#overview)
- [Installation](#installation)
- [Development](#development)
- [Additional Information](#additional-information)
- [License](#license)

## Overview
RepoRemedy aims to lower the barrier to software engineering best practices in
open-source repositories. It will turn RepoAuditor text and OpenSSF Scorecard JSON
findings into reviewable issues and pull requests.

### How to use `RepoRemedy`
Read an existing report and write normalized findings and source provenance as JSON:

```shell
RepoRemedy inspect report.json --report-type ossf-scorecard --repo acme/demo
RepoRemedy inspect report.txt --report-type repoauditor --repo https://github.gatech.edu/sse-center/sse-resources
```

Use `RepoRemedy inspect --help` for inspection options and `RepoRemedy --version` for the installed
version. `OWNER/REPO` means GitHub.com; use an HTTPS URL or `HOST/OWNER/REPO` for
GitHub Enterprise. Enterprise hosts are retained in the output and Scorecard scan
matching, including non-default HTTPS ports.

Gather context and create concrete remedy proposals from an audit report:

```shell
RepoRemedy propose report.json --report-type ossf-scorecard --repo OWNER/REPO > proposals.json
```

`propose` reads the audited commit when recorded, otherwise `main`. Use `--ref main`
or a full commit SHA to select a revision explicitly. It resolves catalog inputs
and renders an issue or an eligible draft PR, including file contents and diffs.
Missing inputs and blocked proposals remain visible. Publication is a separate,
planned `publish` step; `propose` makes no GitHub changes.

See [proposing remedies](doc/repository-context.md) for authentication, collected
context, maintainer inputs, PR guards and the saved proposal contract.

Generate proposals for several repositories using report-path templates:

```shell
RepoRemedy propose-batch demo/batch.json --output batch-results
```

The [batch workflow](doc/batch.md) uses the same remediation behavior as `propose`,
preserves each repository's bundles and summary, and continues after input failures.
Exit code `3` identifies partial failure; output directories must be new.

<!-- Content below this delimiter will be copied to the generated README.md file. DO NOT REMOVE THIS COMMENT, as it will cause regeneration to fail. -->

## Installation

| Installation Method | Command |
| --- | --- |
| Via [uv](https://github.com/astral-sh/uv) | `uv add RepoRemedy` |
| Via [pip](https://pip.pypa.io/en/stable/) | `pip install RepoRemedy` |

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
`RepoRemedy` is licensed under the <a href="https://choosealicense.com/licenses/MIT/" target="_blank">MIT</a> license.
