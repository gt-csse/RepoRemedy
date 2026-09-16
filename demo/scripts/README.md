# Generate audit reports

Requires Linux/macOS, Python 3.14+, and separately installed `RepoAuditor` and
OpenSSF `scorecard` executables. The runner uses Python's standard library and
does not require RepoRemedy's report-reader branch.

From the repository root:

```bash
export GITHUB_TOKEN="$(gh auth token --hostname github.com --user ketanbj)"
python3 demo/scripts/run_audits.py demo/scripts/repositories.json \
  --output /tmp/reporemedy-audits-new \
  --repoauditor /path/to/RepoAuditor/.venv/bin/RepoAuditor \
  --scorecard /path/to/scorecard
```

Replace the executable paths, or omit those options when both tools are on `PATH`.
The output directory must not exist. Use `--help` for options; defaults are two
parallel repositories, a 900-second timeout per scan, and no retries. `--retries 1`
retries failed scans/API requests once and keeps each scan attempt's artifacts.

**Input:** `repositories.json` is a JSON array of `OWNER/REPO` names. Replace it
with another list for an organization-wide batch. Repository discovery is separate.

**Output:** `manifest.json` records tool versions, default branches, commands,
timestamps, exit codes, report hashes, and attempts. Reports and logs are stored
under `OWNER/REPO/attempt-N/`. The existing demo reports are not read or replaced.
The manifest is output only; it is not a RepoRemedy input report.

RepoAuditor runs the GitHub, CommunityStandards, and ScientificSoftware modules;
Scorecard runs its default checks with JSON details. Exit 255 from RepoAuditor is
accepted only when its report passes basic export checks. `report_written` means
execution and basic checks succeeded, **not** that findings or report completeness
were validated by RepoRemedy. Reader validation remains a separate step.

The runner exits **0** when both reports are written for every repository, **1**
when any scan fails, and **2** for setup/argument errors. Inspect the manifest and
logs for failures and missing evidence. Settings and cloned files are read at
different times; the batch is not an atomic snapshot.

`GITHUB_TOKEN` authenticates metadata requests, RepoAuditor's GitHub module, and
Scorecard. Repository-file clones use anonymous access, so this template targets
public GitHub.com repositories. `--anonymous` explicitly disables token use and
may yield limited evidence or rate-limit failures. Authentication failures are
recorded without silently switching to anonymous scans. A private temporary token
file is removed after the batch; review generated artifacts before sharing them.
