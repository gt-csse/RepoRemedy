# Live demo fixture reports

Authenticated audit exports for [ketanbj/reporemedy-live-fixture](https://github.com/ketanbj/reporemedy-live-fixture), generated 24 September 2026.

| Source | Export | RepoRemedy findings |
| --- | --- | --- |
| RepoAuditor 0.4.8 | [repoauditor.txt](repoauditor.txt) | 33 |
| OpenSSF Scorecard 5.5.0 | [scorecard.json](scorecard.json) | 15 (12 gaps, 3 unavailable) |

Follow the [illustrated interactive demo](../../../../doc/demo/interactive-live.md) from a fresh clone. It uses these saved reports; installing and running the auditors is optional.

[manifest.json](manifest.json) records versions, module selection, checksums and reader validation. The fixture is deliberately incomplete. The reports describe its state at capture time; live publication checks still run against GitHub. This fixture is separate from the original ten-repository cohort in `demo/batch.json` and `demo/reports/manifest.json`.
