# Interactive single-repository remediation

Start with an existing RepoAuditor or OpenSSF Scorecard report:

```shell
uv run RepoRemedy inspect report.txt --report-type repoauditor \
  --repo OWNER/REPO --interactive --plan remedy-plan.json
```

Use `--report-type ossf-scorecard` for Scorecard JSON. The report is read offline
first. Browse findings and evidence, then choose **Select remedies** to collect
repository context. Collection uses the audited commit when recorded, otherwise
`main`, just like the existing proposal workflow. Set `REPOREMEDY_TOKEN` in your
environment before continuing, or use `--token-env ENTERPRISE_TOKEN` for another
host-appropriate variable. Tokens are never stored in the plan.

The terminal interface uses [Textual](https://textual.textualize.io/). It supports
keyboard navigation and mouse input. `Tab` moves between controls; arrow keys
browse lists; `Space` toggles a remedy or checkbox. `Ctrl+S` saves the session and
`Ctrl+Q` saves and exits. The same actions are available as labeled buttons.

## Select and review

1. Search remedy IDs or report evidence. Filter by readiness or selection.
2. Select individual remedies, or select/clear all eligible remedies in the
   current filter. Selections outside the filter stay intact.
3. Choose **Review**. Each selected proposal shows evidence, reasons, the issue
   body and any exact file diffs. **Back** returns to the selection list.
4. Use **Edit inputs / route** to choose an issue or an available draft PR route.
   Fill the catalog fields, approve those values, and generate the preview.
5. Choose **Approve / next** for each ready proposal, or deselect it. Input
   approval and content review are separate. Changing inputs or routes clears
   the affected content review. Blocked proposals cannot be approved.

The UI offers a draft PR for catalog remedies with a PR definition and shows why
it is not yet ready. This avoids silently falling back to an issue while a user
is completing PR inputs. Existing-file edits and the catalog's unsupported PR
routes remain blocked. The user can explicitly choose an issue instead.

Unsupported or unavailable findings remain visible. Multiple findings with the
same remedy ID are marked not selectable because the current publisher requires
one unambiguous proposal. This increment does not combine audit sources or
discard duplicate evidence. Use one report for one repository per plan.

## Save and resume

```shell
uv run RepoRemedy inspect --resume remedy-plan.json
```

The versioned JSON plan embeds the existing proposal bundle, selections, inputs,
route choices and exact-content review digests. It is written atomically and can
also be saved before context collection or before all inputs/reviews are complete.
An existing plan is never replaced by a new inspection; resume it or choose a
different `--plan` path. Use one session per plan file at a time.

The plan contains local report/context evidence and proposed content. Keep it
local for review; the publisher sends only selected issue/PR content. The receipt
path defaults to `publication-receipts.json` beside the plan, and is a typed path
in the plan schema. Use separate directories or distinct receipt paths for
different repositories. Relative receipt paths resolve against the plan location.

## Publish the reviewed plan

Choose **Publish** from the selection screen, or reopen directly at confirmation:

```shell
uv run RepoRemedy publish --plan remedy-plan.json
```

Every selected proposal must be ready and reviewed. The screen names the target
repository and expected issue/draft-PR counts. Check the confirmation box and
choose **Publish selected**. Selecting or reviewing remedies never publishes.

The existing publisher checks target freshness and permissions before each new
publication, reuses matching existing objects, and records each completed result
before proceeding. The UI shows progress, created/reused results and their actual
links. Select a result and choose **Open selected result** to view it in a browser.
Draft PRs require maintainer review and merging; issues request maintainer action.
Repository settings are not changed automatically.

If publication stops, completed results and the plan remain available. Inspect
the receipt journal before retrying the same command. Confirm each retry; matching
existing objects are reused. Uncertain attempts still require reconciliation and
are never blindly recreated. A stale branch or changed catalog requires generating
and reviewing a new plan from an appropriate audit; resuming does not refresh or
silently approve changed content. See [publication rules](publishing.md).

For automation, explicit confirmation publishes the saved selections and emits
the existing receipt JSON format:

```shell
uv run RepoRemedy publish --plan remedy-plan.json --confirm
```

The plan supplies repository, selections, receipt path and token-variable name.
Do not mix `--plan` with the legacy bundle/selection arguments. The UI requires a
terminal; JSON `inspect`, `propose`, `propose-batch` and legacy `publish` remain
available unchanged for scripts. LLM-assisted proposals and cohort UI are outside
this increment.

## Tests and module boundaries

`plan.py` owns saved state and review validity. `review.py` provides library form
and preview controls. `tui.py` coordinates screens and background workers.
`interactive.py` adapts the CLI. The only publisher extension is an optional
callback after a completed receipt is durably saved; validation and retry rules
remain in the existing publisher.

```shell
uv run pytest tests/plan_test.py tests/interactive_test.py tests/review_test.py tests/tui_test.py --no-cov
```

Tests run the real Textual controls headlessly, with simulated GitHub responses,
including selection across filters, input completion, review invalidation,
save/resume, explicit confirmation, publication and duplicate reuse. They do not
create live GitHub objects.
