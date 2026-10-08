# Generating Input Reports
RepoRemedy reads saved [RepoAuditor](https://github.com/gt-csse/RepoAuditor) text reports
and [OpenSSF Scorecard](https://github.com/ossf/scorecard) JSON reports. This page shows
how to produce each one.

- [RepoAuditor](#repoauditor)
- [OpenSSF Scorecard](#openssf-scorecard)

## RepoAuditor

### Install RepoAuditor
RepoAuditor requires Python 3.10+ and works best with [uv](https://docs.astral.sh/uv/).

`uvx` can be used to run the latest release without a separate install:

```shell
uvx RepoAuditor --version
```

To install it instead, use `uv add repoauditor` or `pip install repoauditor`.

### Create a GitHub token
The `GitHub` module needs a Personal Access Token saved in a file. See
[PAT.md](https://github.com/gt-csse/RepoAuditor/blob/main/docs/PAT.md) for the required scopes. Remember to keep the token file out of the repository!

### Run the audit
Run all three modules against one repository and branch, and save the report with `--output`:

```shell
uvx RepoAuditor \
  --include GitHub             --GitHub-url             https://github.com/OWNER/REPO --GitHub-branch             main \
  --include CommunityStandards --CommunityStandards-url https://github.com/OWNER/REPO --CommunityStandards-branch main \
  --include ScientificSoftware --ScientificSoftware-url https://github.com/OWNER/REPO --ScientificSoftware-branch main \
  --GitHub-pat ~/PAT.txt \
  --output repoauditor.txt
```

- Use the repository's default branch, and the same URL and branch for every module.
- For GitHub Enterprise, use the Enterprise URL and a token issued by that host.
- Use `--exclude Module` or `--exclude Module-Requirement` to skip checks. Run `uvx RepoAuditor --help` to see every option.
- Exit code `255` means RepoAuditor found problems. It does not mean the run failed. Check that the report ends with a complete panel for each module.

### Feed RepoAuditor output to RepoRemedy
Pass the same repository the audit used:

```shell
RepoRemedy inspect repoauditor.txt --report-type repoauditor --repo gt-csse/reporemedy-live-fixture
RepoRemedy propose repoauditor.txt --report-type repoauditor --repo gt-csse/reporemedy-live-fixture > proposals.json
```

RepoRemedy rejects reports that are truncated, edited, or that mix more than one repository or branch. Save each repository's report to its own file. Do not copy the report from a terminal, which can wrap or cut off the panels.

### RepoAuditor example
If we want to audit [gt-csse/reporemedy-live-fixture](https://github.com/gt-csse/reporemedy-live-fixture) on its default branch, `main`, with a GH PAT token saved in `~/PAT.txt`:

```shell
uvx RepoAuditor \
  --include GitHub             --GitHub-url             https://github.com/gt-csse/reporemedy-live-fixture --GitHub-branch             main \
  --include CommunityStandards --CommunityStandards-url https://github.com/gt-csse/reporemedy-live-fixture --CommunityStandards-branch main \
  --include ScientificSoftware --ScientificSoftware-url https://github.com/gt-csse/reporemedy-live-fixture --ScientificSoftware-branch main \
  --GitHub-pat ~/PAT.txt \
  --output repoauditor.txt

RepoRemedy inspect repoauditor.txt --report-type repoauditor --repo gt-csse/reporemedy-live-fixture
RepoRemedy propose repoauditor.txt --report-type repoauditor --repo gt-csse/reporemedy-live-fixture > proposals.json
```

## OpenSSF Scorecard

### Install Scorecard
Use one of these methods. RepoRemedy reads only Scorecard **v5** output.

| Method | Command |
| --- | --- |
| Homebrew (macOS/Linux) | `brew install scorecard` |
| Release binary | Download it from the [releases page](https://github.com/ossf/scorecard/releases/latest) and add it to your `PATH` |
| Docker | `docker pull ghcr.io/ossf/scorecard:latest` |

Check the installed version with `scorecard version`. Scorecard officially supports macOS and Linux. On Windows, use Docker or WSL.

### Set a GitHub token
Scorecard reads a GitHub token from the environment. A classic token with `public_repo` scope works for public repositories:

```shell
export GITHUB_AUTH_TOKEN=<token>
```

For GitHub Enterprise Server, also set the host name, without `https://`:

```shell
export GH_HOST=github.example.com
```

### Run the scan
Write JSON with details to a file. Progress messages go to stderr, so they stay out of
the report:

```shell
scorecard --repo=github.com/gt-csse/reporemedy-live-fixture --format=json --show-details > scorecard.json
```

With Docker:

```shell
docker run --rm -e GITHUB_AUTH_TOKEN ghcr.io/ossf/scorecard:latest \
  --repo=github.com/gt-csse/reporemedy-live-fixture --format=json --show-details > scorecard.json
```

- Use `--checks=Name1,Name2` to run only some checks.
- A score of `-1` means Scorecard could not collect the evidence. It does not mean the
  check failed.

### Feed Scorecard output to RepoRemedy
Pass the same repository the scan used:

```shell
RepoRemedy inspect scorecard.json --report-type ossf-scorecard --repo gt-csse/reporemedy-live-fixture
RepoRemedy propose scorecard.json --report-type ossf-scorecard --repo gt-csse/reporemedy-live-fixture > proposals.json
```

The report must contain exactly one scan for that repository. RepoRemedy records the commit that Scorecard scanned, and `propose` reads the repository at that commit.

### Scorecard example
Scan [gt-csse/reporemedy-live-fixture](https://github.com/gt-csse/reporemedy-live-fixture) with `GITHUB_AUTH_TOKEN` already set:

```shell
scorecard --repo=github.com/gt-csse/reporemedy-live-fixture --format=json --show-details > scorecard.json

RepoRemedy inspect scorecard.json --report-type ossf-scorecard --repo gt-csse/reporemedy-live-fixture
RepoRemedy propose scorecard.json --report-type ossf-scorecard --repo gt-csse/reporemedy-live-fixture > proposals.json
```

With Docker, replace the `scorecard` line with:

```shell
docker run --rm -e GITHUB_AUTH_TOKEN ghcr.io/ossf/scorecard:latest \
  --repo=github.com/gt-csse/reporemedy-live-fixture --format=json --show-details > scorecard.json
```

## Examples
[`demo/reports`](../demo/reports) contains real reports from both tools. Its
[`manifest.json`](../demo/reports/manifest.json) records the exact command and tool version
used for each report.
