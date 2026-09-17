# Remedy catalog

Potential issues from **RepoAuditor (RA)** and **OpenSSF Scorecard (OSSF)**,
organized as **issue | type | response | origin**. These are review candidates;
each response names its stable remedy ID and links to its topic catalog. [`propose`](repository-context.md) gathers context and renders these remedies; publication remains a separate, planned step.

Types: **Documentation**, **Settings**, **Configuration**, **Engineering**, or
**Manual** (a maintainer decision). File changes become draft PRs; settings responses
become administrator instructions. Confirm current evidence and project policy first.

This catalog retains 62 RA identifiers and 20 OSSF checks across 69 rows.
Related protection checks share rows but can have different meanings or opposite settings.
The 68 remedy definitions are grouped into five topic catalogs and use five shared
body templates. Topic grouping is independent of issue/PR presentation. Every definition supports
an issue; nine also define a file-creation PR. Existing-file
edits require a future editing strategy. See the [template design](design.md#non-llm-templates).

The [catalog README](../src/RepoRemedy/templates/catalog/README.md) explains topic
files, shared bodies, definition fields and how to add or update a remedy.

## Documentation and community

| issue | type | response | origin |
| --- | --- | --- | --- |
| README is missing or not detected (`ReadMe`) | Documentation | Draft a README with verified installation, usage and support information; preserve valid existing documentation. [Template: ra-read-me](../src/RepoRemedy/templates/catalog/documentation.toml). | RA |
| Code of conduct is missing or not detected (`CodeOfConduct`) | Documentation + manual | Draft the agreed conduct policy with a maintainer-approved enforcement contact. [Template: ra-code-of-conduct](../src/RepoRemedy/templates/catalog/documentation.toml). | RA |
| Contribution guidance is missing or not detected (`Contributing`) | Documentation | Document contribution setup, tests and review expectations; verify the commands. [Template: ra-contributing](../src/RepoRemedy/templates/catalog/documentation.toml). | RA |
| License file is missing or not detected (`LicenseFile`) | Documentation + manual | Add the maintainer-selected license with approved attribution; preserve existing valid notices. [Template: ra-license-file](../src/RepoRemedy/templates/catalog/documentation.toml). | RA |
| Security policy is missing or needs attention (`SecurityPolicy`) | Documentation | Add or improve the policy using approved reporting contacts and supported-version information. [Template: security-policy](../src/RepoRemedy/templates/catalog/documentation.toml). | RA |
| Issue templates are missing or not detected (`IssueTemplates`) | Documentation + configuration | Add suitable bug/feature templates and verify the issue creation flow. [Template: ra-issue-templates](../src/RepoRemedy/templates/catalog/documentation.toml). | RA |
| Pull request template is missing or not detected (`PullRequestTemplate`) | Documentation | Add a concise PR template covering purpose, changes and validation. [Template: ra-pull-request-template](../src/RepoRemedy/templates/catalog/documentation.toml). | RA |
| Code ownership is not documented in a recognized file (`CodeOwners`) | Configuration | Define agreed path owners and verify reviewer access and matching patterns. [Template: ra-code-owners](../src/RepoRemedy/templates/catalog/documentation.toml). | RA |
| Citation metadata is missing or not detected (`Citation`) | Documentation + configuration | Add accurate citation metadata from project records and validate its format. [Template: ra-citation](../src/RepoRemedy/templates/catalog/documentation.toml). | RA |

## Repository settings

| issue | type | response | origin |
| --- | --- | --- | --- |
| Repository description is missing or does not meet the audit requirement (`Description`) | Settings | Set a maintainer-approved description in the repository's About section. [Template: ra-description](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Detected license does not match the configured requirement (`License`) | Manual + documentation | Reconcile license detection with project intent; change license content only after maintainer approval. [Template: ra-license](../src/RepoRemedy/templates/catalog/maintainer-decisions.toml). | RA |
| Template-repository status differs from the configured requirement (`TemplateRepository`) | Settings | Align template status with intended repository use and verify the setting. [Template: ra-template-repository](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Web-commit sign-off setting differs from contribution policy (`WebCommitSignoff`) | Settings | Align web sign-off with contribution policy; distinguish sign-off from cryptographic signing. [Template: ra-web-commit-signoff](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Default branch differs from the configured requirement (`DefaultBranch`) | Manual + settings | Confirm the intended default branch and plan changes to CI, protections and integrations before renaming. [Template: ra-default-branch](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Wiki availability differs from documentation policy (`SupportWikis`) | Settings | Align wiki availability with documentation needs; preserve existing content and access. [Template: ra-support-wikis](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Issue-tracker availability differs from support policy (`SupportIssues`) | Settings | Align issue tracking with the support process; preserve existing reports and routing. [Template: ra-support-issues](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Discussion availability differs from community policy (`SupportDiscussions`) | Settings | Configure discussions with agreed moderation and ownership. [Template: ra-support-discussions](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Project-board availability differs from planning policy (`SupportProjects`) | Settings | Align project-board availability with the team's planning process. [Template: ra-support-projects](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Merge-commit availability differs from history policy (`MergeCommit`) | Settings | Align merge methods with history policy and verify a permitted merge path. [Template: ra-merge-commit](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Merge-commit message defaults differ from project conventions (`MergeCommitMessage`) | Settings | Set approved merge-message defaults and preview the generated message. [Template: ra-merge-commit-message](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Squash-merge availability differs from history policy (`SquashCommitMerge`) | Settings | Align squash merging with history policy; verify attribution and protections. [Template: ra-squash-commit-merge](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Squash-commit message defaults differ from project conventions (`SquashMergeCommitMessage`) | Settings | Set squash-message defaults and verify context and attribution. [Template: ra-squash-merge-commit-message](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Rebase-merge availability differs from history policy (`RebaseMergeCommit`) | Settings | Align rebase merging with history policy; verify signature and attribution behavior. [Template: ra-rebase-merge-commit](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Update-branch suggestions differ from the expected workflow (`SuggestUpdatingPullRequestBranches`) | Settings | Configure update-branch suggestions and verify the intended CI workflow. [Template: ra-suggest-updating-pull-request-branches](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Auto-merge availability differs from project policy (`AutoMerge`) | Settings | Align auto-merge availability with policy; verify review and check gates. [Template: ra-auto-merge](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Post-merge branch cleanup differs from project policy (`DeleteHeadBranches`) | Settings | Configure branch cleanup while preserving long-lived branches and dependent work. [Template: ra-delete-head-branches](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Repository visibility differs from the configured requirement (`Private`) | Manual | Confirm intended visibility with the owner; review access and exposure before any change. [Template: ra-private](../src/RepoRemedy/templates/catalog/maintainer-decisions.toml). | RA |
| Dependabot security-update setting needs attention (`DependabotSecurityUpdates`) | Settings | Verify prerequisites and enable security updates when intended; distinguish this from version-update configuration. [Template: ra-dependabot-security-updates](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Secret-scanning setting needs attention (`SecretScanning`) | Settings | Configure available secret scanning; handle exposed secrets privately and rotate them. [Template: ra-secret-scanning](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |
| Secret-scanning push-protection setting needs attention (`SecretScanningPushProtection`) | Settings | Configure push protection and exceptions; validate with harmless test data. [Template: ra-secret-scanning-push-protection](../src/RepoRemedy/templates/catalog/repository-settings.toml). | RA |

## Branch protection

| issue | type | response | origin |
| --- | --- | --- | --- |
| Default-branch protection is absent or not detected (`Protected`) | Settings | Inspect effective branch protection and propose rules suited to the project. [Template: ra-protected](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| PR-before-merge requirement differs from policy (`RequirePullRequests`; `RequirePullRequestsRule`) | Settings | Align PR requirements with policy; verify restricted direct changes and permitted PRs. [Template: ra-require-pull-requests](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Required approval count does not meet the audit requirement (`RequireApprovals`; `RequireApprovalsRule`) | Settings | Set the agreed approval threshold and verify eligible reviewers; respect each check's configured expectations. [Template: ra-require-approvals](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Stale-approval dismissal differs from policy (`DismissStalePullRequestApprovals`; `DismissStalePullRequestApprovalsRule`) | Settings | Configure stale-review dismissal and verify approval behavior after a new push. [Template: ra-dismiss-stale-pull-request-approvals](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Code-owner approval requirement differs from policy (`RequireCodeOwnerReview`; `RequireCodeOwnerReviewRule`) | Settings | Validate CODEOWNERS and reviewer access, then verify required owner approval. [Template: ra-require-code-owner-review](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Approval of the most recent reviewable push differs from policy (`RequireApprovalMostRecentPush`; `RequireApprovalMostRecentPushRule`) | Settings | Require an eligible reviewer other than the last pusher where policy calls for it. [Template: ra-require-approval-most-recent-push](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Required-check enforcement differs from policy (`RequireStatusChecksToPass`; `RequireStatusChecksToPassRule`) | Settings | Require working checks and verify that failing results block merging. [Template: ra-require-status-checks-to-pass](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Up-to-date branch requirement differs from policy (`RequireUpToDateBranches`; `RequireUpToDateBranchesRule`) | Settings | Align branch freshness requirements with the update or merge-queue workflow. [Template: ra-require-up-to-date-branches](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Required status checks are missing or differ from expectations (`EnsureStatusChecks`; `EnsureStatusChecksRule`) | Settings | Configure exact observed check names and source apps; verify both passing and failing outcomes. [Template: ra-ensure-status-checks](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Review-conversation resolution requirement differs from policy (`RequireConversationResolution`; `RequireConversationResolutionRule`) | Settings | Align conversation-resolution requirements with policy and verify an unresolved review thread. [Template: ra-require-conversation-resolution](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Commit-signature requirement differs from policy (`RequireSignedCommits`; `RequireSignedCommitsRule`) | Settings | Configure required signatures and verify contributor/bot support; do not rewrite history automatically. [Template: ra-require-signed-commits](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Linear-history requirement differs from policy (`RequireLinearHistory`; `RequireLinearHistoryRule`) | Settings | Align linear-history enforcement with supported merge methods and signature requirements. [Template: ra-require-linear-history](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Administrator bypass of classic protection differs from policy (`DoNotAllowBypassSettings`) | Settings | Review administrator bypass and emergency access; verify the intended restrictions. [Template: ra-do-not-allow-bypass-settings](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Branch-deletion permissions differ from policy (`AllowDeletions`; `RestrictDeletionsRule`) | Settings | Align deletion rules with policy; account for opposite check polarity and use a test branch. [Template: ra-allow-deletions](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Force-push permissions differ from policy (`AllowMainlineForcePushes`; `BlockMainlineForcePushesRule`) | Settings | Align force-push rules and exceptions; account for opposite polarity without rewriting shared history. [Template: ra-allow-mainline-force-pushes](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Ref-creation restrictions differ from policy (`RestrictCreationsRule`) | Settings | Set ref-creation restrictions for agreed patterns and authorized actors. [Template: ra-restrict-creations-rule](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Ref-update restrictions differ from policy (`RestrictUpdatesRule`) | Settings | Set ref-update restrictions while preserving legitimate release and automation access. [Template: ra-restrict-updates-rule](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Required successful deployments differ from policy (`RequireSuccessfulDeploymentsRule`) | Settings | Select working deployment environments and verify that missing or failed deployments block merging. [Template: ra-require-successful-deployments-rule](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |
| Required code-scanning results differ from policy (`RequireCodeScanningResultsRule`) | Settings | Configure scanner requirements and thresholds; validate the gate with controlled results. [Template: ra-require-code-scanning-results-rule](../src/RepoRemedy/templates/catalog/branch-protection.toml). | RA |

## OpenSSF Scorecard

| issue | type | response | origin |
| --- | --- | --- | --- |
| Binary artifacts in the repository need review (`Binary-Artifacts`) | Manual + engineering | Review binary provenance and usage; validate replacements before removing needed artifacts. [Template: ossf-binary-artifacts](../src/RepoRemedy/templates/catalog/engineering.toml). | OSSF |
| Branch-protection evidence indicates possible gaps (`Branch-Protection`) | Settings | Inspect effective rules and propose only the specific protections supported by evidence. [Template: ossf-branch-protection](../src/RepoRemedy/templates/catalog/branch-protection.toml). | OSSF |
| Successful CI tests are insufficient or not detected (`CI-Tests`) | Documentation + engineering | Establish useful tests and reproducible CI execution; investigate detector mismatches. [Template: ossf-ci-tests](../src/RepoRemedy/templates/catalog/engineering.toml). | OSSF |
| Best-practices badge evidence is missing or below the desired level (`CII-Best-Practices`) | Manual | Assign an owner to assess badge criteria and address evidenced gaps. [Template: ossf-cii-best-practices](../src/RepoRemedy/templates/catalog/maintainer-decisions.toml). | OSSF |
| Code-review evidence indicates possible gaps (`Code-Review`) | Settings + manual | Improve review practices and requirements; distinguish future enforcement from historical evidence. [Template: ossf-code-review](../src/RepoRemedy/templates/catalog/branch-protection.toml). | OSSF |
| Contributor participation evidence needs review (`Contributors`) | Manual + documentation | Review participation barriers and improve onboarding in line with maintainer goals. [Template: ossf-contributors](../src/RepoRemedy/templates/catalog/maintainer-decisions.toml). | OSSF |
| Workflow contains a reported dangerous pattern (`Dangerous-Workflow`) | Engineering | Repair the identified workflow pattern and validate its trigger, permissions and trust boundaries. [Template: ossf-dangerous-workflow](../src/RepoRemedy/templates/catalog/engineering.toml). | OSSF |
| Dependency-update tooling is missing or not detected (`Dependency-Update-Tool`) | Configuration | Configure an appropriate updater for actual ecosystems and directories; verify a representative update. [Template: ossf-dependency-update-tool](../src/RepoRemedy/templates/catalog/engineering.toml). | OSSF |
| Fuzzing coverage is missing or not detected (`Fuzzing`) | Manual + engineering | Choose useful fuzz targets, maintainable harnesses and owners; demonstrate execution and failure reporting. [Template: ossf-fuzzing](../src/RepoRemedy/templates/catalog/engineering.toml). | OSSF |
| License evidence is missing or not recognized (`License`) | Manual + documentation | Resolve absent or unrecognized licensing using maintainer-approved content. [Template: ossf-license](../src/RepoRemedy/templates/catalog/maintainer-decisions.toml). | OSSF |
| Maintenance activity indicates a possible continuity gap (`Maintained`) | Manual | Agree an honest support, ownership, continuity or archival plan with maintainers. [Template: ossf-maintained](../src/RepoRemedy/templates/catalog/maintainer-decisions.toml). | OSSF |
| Package-publication evidence is missing or incomplete (`Packaging`) | Documentation + engineering | Establish reproducible package publication where appropriate and validate the resulting artifacts. [Template: ossf-packaging](../src/RepoRemedy/templates/catalog/engineering.toml). | OSSF |
| Dependency references are mutable or insufficiently pinned (`Pinned-Dependencies`) | Engineering | Replace mutable references with verified immutable versions; test compatibility and plan updates. [Template: ossf-pinned-dependencies](../src/RepoRemedy/templates/catalog/engineering.toml). | OSSF |
| Static-analysis evidence indicates possible gaps (`SAST`) | Settings + engineering | Configure suitable static analysis and verify useful results; a merge gate alone is insufficient. [Template: ossf-sast](../src/RepoRemedy/templates/catalog/engineering.toml). | OSSF |
| Software bill of materials is missing or not detected (`SBOM`) | Engineering | Generate an accurate SBOM, validate it and update it with releases. [Template: ossf-sbom](../src/RepoRemedy/templates/catalog/engineering.toml). | OSSF |
| Security policy is missing or may be inadequate (`Security-Policy`) | Documentation | Add or improve the policy using approved contacts and support statements. [Template: security-policy](../src/RepoRemedy/templates/catalog/documentation.toml). | OSSF |
| Release-signing evidence is missing or incomplete (`Signed-Releases`) | Engineering | Establish artifact signing/provenance and verify it; distinguish release signatures from commit signatures. [Template: ossf-signed-releases](../src/RepoRemedy/templates/catalog/engineering.toml). | OSSF |
| Workflow token permissions may be broader than necessary (`Token-Permissions`) | Engineering | Reduce workflow-token permissions to demonstrated job needs and verify workflows still run. [Template: ossf-token-permissions](../src/RepoRemedy/templates/catalog/engineering.toml). | OSSF |
| Reported vulnerabilities need triage (`Vulnerabilities`) | Manual + engineering | Triage exact advisories and dependency paths; test supported fixes and handle sensitive findings privately. [Template: ossf-vulnerabilities](../src/RepoRemedy/templates/catalog/engineering.toml). | OSSF |
| Webhook authentication configuration needs review (`Webhooks`) | Settings + manual | Assign private webhook authentication setup and verification to an authorized maintainer; include only configuration status and non-secret results in the proposal. [Template: ossf-webhooks](../src/RepoRemedy/templates/catalog/repository-settings.toml). | OSSF |

## Using and extending the catalog

- Keep the exact source identifier and evidence with each issue. Passing, unavailable
  and omitted checks do not establish defects; leave unknown checks visible for review.
- Combine overlapping findings only when they support the same change to the same target.
- Add a row with the issue/check, type, linked template response and `RA` or `OSSF`.
  Add the uniquely keyed definition to its topic catalog, select a shared body,
  provide remedy-specific guidance and any proposed-file assets,
  and declare the exact source identifiers and required inputs.
- Obtain maintainer inputs such as contacts, license choices and owners. Review new
  handlers against missing, already-correct, conflicting and unavailable cases.

See [design.md](design.md) for report handling.

## Sources

- [RepoAuditor checks](https://github.com/gt-csse/RepoAuditor/tree/main/src/RepoAuditor/Plugins)
- [OpenSSF Scorecard checks](https://github.com/ossf/scorecard/blob/main/docs/checks.md)
- [Audit reports and remedy helpers](https://github.com/gt-ospo/oss-security-audit-tools)
