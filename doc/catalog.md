# Remedy catalog

Potential issues from **RepoAuditor (RA)** and **OpenSSF Scorecard (OSSF)**,
organized as **issue | type | response | origin**. These are review candidates;
listing a remedy does not mean it is implemented.

Types: **Documentation**, **Settings**, **Configuration**, **Engineering**, or
**Manual** (a maintainer decision). File changes become draft PRs; settings responses
become administrator instructions. Confirm current evidence and project policy first.

This catalog retains 62 RA identifiers and 20 OSSF checks across 69 rows.
Related protection checks share rows but can have different meanings or opposite settings.

## Documentation and community

| issue | type | response | origin |
| --- | --- | --- | --- |
| README is missing or not detected (`ReadMe`) | Documentation | Draft a README with verified installation, usage and support information; preserve valid existing documentation. | RA |
| Code of conduct is missing or not detected (`CodeOfConduct`) | Documentation + manual | Draft the agreed conduct policy with a maintainer-approved enforcement contact. | RA |
| Contribution guidance is missing or not detected (`Contributing`) | Documentation | Document contribution setup, tests and review expectations; verify the commands. | RA |
| License file is missing or not detected (`LicenseFile`) | Documentation + manual | Add the maintainer-selected license with approved attribution; preserve existing valid notices. | RA |
| Security policy is missing or needs attention (`SecurityPolicy`) | Documentation | Add or improve the policy using approved reporting contacts and supported-version information. | RA |
| Issue templates are missing or not detected (`IssueTemplates`) | Documentation + configuration | Add suitable bug/feature templates and verify the issue creation flow. | RA |
| Pull request template is missing or not detected (`PullRequestTemplate`) | Documentation | Add a concise PR template covering purpose, changes and validation. | RA |
| Code ownership is not documented in a recognized file (`CodeOwners`) | Configuration | Define agreed path owners and verify reviewer access and matching patterns. | RA |
| Citation metadata is missing or not detected (`Citation`) | Documentation + configuration | Add accurate citation metadata from project records and validate its format. | RA |

## Repository settings

| issue | type | response | origin |
| --- | --- | --- | --- |
| Repository description is missing or does not meet the audit requirement (`Description`) | Settings | Set a maintainer-approved description in the repository's About section. | RA |
| Detected license does not match the configured requirement (`License`) | Manual + documentation | Reconcile license detection with project intent; change license content only after maintainer approval. | RA |
| Template-repository status differs from the configured requirement (`TemplateRepository`) | Settings | Align template status with intended repository use and verify the setting. | RA |
| Web-commit sign-off setting differs from contribution policy (`WebCommitSignoff`) | Settings | Align web sign-off with contribution policy; distinguish sign-off from cryptographic signing. | RA |
| Default branch differs from the configured requirement (`DefaultBranch`) | Manual + settings | Confirm the intended default branch and plan changes to CI, protections and integrations before renaming. | RA |
| Wiki availability differs from documentation policy (`SupportWikis`) | Settings | Align wiki availability with documentation needs; preserve existing content and access. | RA |
| Issue-tracker availability differs from support policy (`SupportIssues`) | Settings | Align issue tracking with the support process; preserve existing reports and routing. | RA |
| Discussion availability differs from community policy (`SupportDiscussions`) | Settings | Configure discussions with agreed moderation and ownership. | RA |
| Project-board availability differs from planning policy (`SupportProjects`) | Settings | Align project-board availability with the team's planning process. | RA |
| Merge-commit availability differs from history policy (`MergeCommit`) | Settings | Align merge methods with history policy and verify a permitted merge path. | RA |
| Merge-commit message defaults differ from project conventions (`MergeCommitMessage`) | Settings | Set approved merge-message defaults and preview the generated message. | RA |
| Squash-merge availability differs from history policy (`SquashCommitMerge`) | Settings | Align squash merging with history policy; verify attribution and protections. | RA |
| Squash-commit message defaults differ from project conventions (`SquashMergeCommitMessage`) | Settings | Set squash-message defaults and verify context and attribution. | RA |
| Rebase-merge availability differs from history policy (`RebaseMergeCommit`) | Settings | Align rebase merging with history policy; verify signature and attribution behavior. | RA |
| Update-branch suggestions differ from the expected workflow (`SuggestUpdatingPullRequestBranches`) | Settings | Configure update-branch suggestions and verify the intended CI workflow. | RA |
| Auto-merge availability differs from project policy (`AutoMerge`) | Settings | Align auto-merge availability with policy; verify review and check gates. | RA |
| Post-merge branch cleanup differs from project policy (`DeleteHeadBranches`) | Settings | Configure branch cleanup while preserving long-lived branches and dependent work. | RA |
| Repository visibility differs from the configured requirement (`Private`) | Manual | Confirm intended visibility with the owner; review access and exposure before any change. | RA |
| Dependabot security-update setting needs attention (`DependabotSecurityUpdates`) | Settings | Verify prerequisites and enable security updates when intended; distinguish this from version-update configuration. | RA |
| Secret-scanning setting needs attention (`SecretScanning`) | Settings | Configure available secret scanning; handle exposed secrets privately and rotate them. | RA |
| Secret-scanning push-protection setting needs attention (`SecretScanningPushProtection`) | Settings | Configure push protection and exceptions; validate with harmless test data. | RA |

## Branch protection

| issue | type | response | origin |
| --- | --- | --- | --- |
| Default-branch protection is absent or not detected (`Protected`) | Settings | Inspect effective branch protection and propose rules suited to the project. | RA |
| PR-before-merge requirement differs from policy (`RequirePullRequests`; `RequirePullRequestsRule`) | Settings | Align PR requirements with policy; verify restricted direct changes and permitted PRs. | RA |
| Required approval count does not meet the audit requirement (`RequireApprovals`; `RequireApprovalsRule`) | Settings | Set the agreed approval threshold and verify eligible reviewers; respect each check's configured expectations. | RA |
| Stale-approval dismissal differs from policy (`DismissStalePullRequestApprovals`; `DismissStalePullRequestApprovalsRule`) | Settings | Configure stale-review dismissal and verify approval behavior after a new push. | RA |
| Code-owner approval requirement differs from policy (`RequireCodeOwnerReview`; `RequireCodeOwnerReviewRule`) | Settings | Validate CODEOWNERS and reviewer access, then verify required owner approval. | RA |
| Approval of the most recent reviewable push differs from policy (`RequireApprovalMostRecentPush`; `RequireApprovalMostRecentPushRule`) | Settings | Require an eligible reviewer other than the last pusher where policy calls for it. | RA |
| Required-check enforcement differs from policy (`RequireStatusChecksToPass`; `RequireStatusChecksToPassRule`) | Settings | Require working checks and verify that failing results block merging. | RA |
| Up-to-date branch requirement differs from policy (`RequireUpToDateBranches`; `RequireUpToDateBranchesRule`) | Settings | Align branch freshness requirements with the update or merge-queue workflow. | RA |
| Required status checks are missing or differ from expectations (`EnsureStatusChecks`; `EnsureStatusChecksRule`) | Settings | Configure exact observed check names and source apps; verify both passing and failing outcomes. | RA |
| Review-conversation resolution requirement differs from policy (`RequireConversationResolution`; `RequireConversationResolutionRule`) | Settings | Align conversation-resolution requirements with policy and verify an unresolved review thread. | RA |
| Commit-signature requirement differs from policy (`RequireSignedCommits`; `RequireSignedCommitsRule`) | Settings | Configure required signatures and verify contributor/bot support; do not rewrite history automatically. | RA |
| Linear-history requirement differs from policy (`RequireLinearHistory`; `RequireLinearHistoryRule`) | Settings | Align linear-history enforcement with supported merge methods and signature requirements. | RA |
| Administrator bypass of classic protection differs from policy (`DoNotAllowBypassSettings`) | Settings | Review administrator bypass and emergency access; verify the intended restrictions. | RA |
| Branch-deletion permissions differ from policy (`AllowDeletions`; `RestrictDeletionsRule`) | Settings | Align deletion rules with policy; account for opposite check polarity and use a test branch. | RA |
| Force-push permissions differ from policy (`AllowMainlineForcePushes`; `BlockMainlineForcePushesRule`) | Settings | Align force-push rules and exceptions; account for opposite polarity without rewriting shared history. | RA |
| Ref-creation restrictions differ from policy (`RestrictCreationsRule`) | Settings | Set ref-creation restrictions for agreed patterns and authorized actors. | RA |
| Ref-update restrictions differ from policy (`RestrictUpdatesRule`) | Settings | Set ref-update restrictions while preserving legitimate release and automation access. | RA |
| Required successful deployments differ from policy (`RequireSuccessfulDeploymentsRule`) | Settings | Select working deployment environments and verify that missing or failed deployments block merging. | RA |
| Required code-scanning results differ from policy (`RequireCodeScanningResultsRule`) | Settings | Configure scanner requirements and thresholds; validate the gate with controlled results. | RA |

## OpenSSF Scorecard

| issue | type | response | origin |
| --- | --- | --- | --- |
| Binary artifacts in the repository need review (`Binary-Artifacts`) | Manual + engineering | Review binary provenance and usage; validate replacements before removing needed artifacts. | OSSF |
| Branch-protection evidence indicates possible gaps (`Branch-Protection`) | Settings | Inspect effective rules and propose only the specific protections supported by evidence. | OSSF |
| Successful CI tests are insufficient or not detected (`CI-Tests`) | Documentation + engineering | Establish useful tests and reproducible CI execution; investigate detector mismatches. | OSSF |
| Best-practices badge evidence is missing or below the desired level (`CII-Best-Practices`) | Manual | Assign an owner to assess badge criteria and address evidenced gaps. | OSSF |
| Code-review evidence indicates possible gaps (`Code-Review`) | Settings + manual | Improve review practices and requirements; distinguish future enforcement from historical evidence. | OSSF |
| Contributor participation evidence needs review (`Contributors`) | Manual + documentation | Review participation barriers and improve onboarding in line with maintainer goals. | OSSF |
| Workflow contains a reported dangerous pattern (`Dangerous-Workflow`) | Engineering | Repair the identified workflow pattern and validate its trigger, permissions and trust boundaries. | OSSF |
| Dependency-update tooling is missing or not detected (`Dependency-Update-Tool`) | Configuration | Configure an appropriate updater for actual ecosystems and directories; verify a representative update. | OSSF |
| Fuzzing coverage is missing or not detected (`Fuzzing`) | Manual + engineering | Choose useful fuzz targets, maintainable harnesses and owners; demonstrate execution and failure reporting. | OSSF |
| License evidence is missing or not recognized (`License`) | Manual + documentation | Resolve absent or unrecognized licensing using maintainer-approved content. | OSSF |
| Maintenance activity indicates a possible continuity gap (`Maintained`) | Manual | Agree an honest support, ownership, continuity or archival plan with maintainers. | OSSF |
| Package-publication evidence is missing or incomplete (`Packaging`) | Documentation + engineering | Establish reproducible package publication where appropriate and validate the resulting artifacts. | OSSF |
| Dependency references are mutable or insufficiently pinned (`Pinned-Dependencies`) | Engineering | Replace mutable references with verified immutable versions; test compatibility and plan updates. | OSSF |
| Static-analysis evidence indicates possible gaps (`SAST`) | Settings + engineering | Configure suitable static analysis and verify useful results; a merge gate alone is insufficient. | OSSF |
| Software bill of materials is missing or not detected (`SBOM`) | Engineering | Generate an accurate SBOM, validate it and update it with releases. | OSSF |
| Security policy is missing or may be inadequate (`Security-Policy`) | Documentation | Add or improve the policy using approved contacts and support statements. | OSSF |
| Release-signing evidence is missing or incomplete (`Signed-Releases`) | Engineering | Establish artifact signing/provenance and verify it; distinguish release signatures from commit signatures. | OSSF |
| Workflow token permissions may be broader than necessary (`Token-Permissions`) | Engineering | Reduce workflow-token permissions to demonstrated job needs and verify workflows still run. | OSSF |
| Reported vulnerabilities need triage (`Vulnerabilities`) | Manual + engineering | Triage exact advisories and dependency paths; test supported fixes and handle sensitive findings privately. | OSSF |
| Webhook authentication configuration needs review (`Webhooks`) | Settings + manual | Configure webhook authentication privately and verify sender/receiver behavior; keep secrets out of proposals. | OSSF |

## Using and extending the catalog

- Keep the exact source identifier and evidence with each issue. Passing, unavailable
  and omitted checks do not establish defects; leave unknown checks visible for review.
- Combine overlapping findings only when they support the same change to the same target.
- Add a row with the issue/check, type, a concise action and validation step, and `RA` or `OSSF`.
- Obtain maintainer inputs such as contacts, license choices and owners. Review new
  handlers against missing, already-correct, conflicting and unavailable cases.

See [design.md](design.md) for report handling.

## Sources

- [RepoAuditor checks](https://github.com/gt-csse/RepoAuditor/tree/main/src/RepoAuditor/Plugins)
- [OpenSSF Scorecard checks](https://github.com/ossf/scorecard/blob/main/docs/checks.md)
- [Audit reports and remedy helpers](https://github.com/gt-ospo/oss-security-audit-tools)