---
name: code-review
description: Evaluate every item in a fixed checklist against a set of code changes, with mechanical verification that no item was skipped. Use when the user asks to run the checklist against a change, evaluate changes against the checklist, or check a diff item by item.
metadata:
    version: 0.2.0
---
# Code Review

Evaluates a fixed checklist of code review items against a set of code changes. The governing requirement is that every item is
actually evaluated and none is silently skipped.

A model asked to evaluate N items will emit N rows whether or not it evaluated N, so a self-reported coverage
table cannot detect the failure it exists to catch. Instead: the item list is data (`checklist_items.json`),
agents write per-item records to disk, and `verify_results.py` reconciles the two. The parent resolves scope,
launches agents, runs the verifier, and reports — it never evaluates an item itself.

## Workflow

**1. Resolve the scope.** Default is the current branch: uncommitted work plus everything on the
branch not on mainline. Use a user-named scope (commit range, paths, PR) if given.

```shell
git status --short
git merge-base HEAD main                 # or master / the repo's mainline
git diff --stat <merge-base>
```

Record the exact diff command that reproduces the change; every agent re-runs it. Do not paste diff
contents into the prompts. If the scope is empty, stop and say so.

**2. Read `checklist_items.json`.** It defines batches, and each item carries a fixed `severity` of
`critical`, `high`, `medium`, or `low`. Use its batching as-is — do not regroup, split, or drop
batches. Create `<scratchpad>/checklist-run/results/`.

**3. Fan out, one agent per batch.** Fill the placeholders in `agent_prompt.md` and launch one
`Agent` call per batch, all in a single message. Each agent gets only its own items, the scope, the
diff command, and an absolute `{{RESULTS_PATH}}` of `results/<BATCH_ID>.json`. Do not reduce the
batch set to save tokens — an item not sent is an item the verifier reports as unevaluated.

**4. Verify.** This gates the report.

```shell
uv run --no-project "<skill-dir>/verify_results.py" "<scratchpad>/checklist-run/results"
```

Exit 0 only when every item has exactly one well-formed record; otherwise it names the IDs that are
missing, duplicated, unknown, or malformed. Do not report while it is failing, regardless of how
complete the agents' replies looked.

On failure, `SendMessage` the owning agent naming only the affected IDs and asking it to append or
correct those records — its context is still loaded. Never write or edit a record yourself to make
the verifier pass. Re-run the verifier after each round. If an agent still cannot produce a valid
record after a second attempt, report the run as FAILED under "Unevaluated items". If Python is
unavailable, stop rather than reconciling by hand.

**5. Report.** Only after exit 0, and built from the record files joined to `checklist_items.json`,
not the agents' reply text. Each failing item goes under the heading matching its `severity` from
`checklist_items.json`; severity is a property of the item, not a judgment the agent makes. Omit a
severity heading that has no failures.

## Output Format

```
# Checklist Results

**Scope:** <what was evaluated>
**Diff command:** `<command>`
**Items:** <N> across <M> batches

## Verification
<verbatim verify_results.py output>

## All Results
| ID | Category | Item | Severity | Population | Verdict | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | Category A | <item text> | high | 2 | pass | <what was examined and observed> |
| …

## Failures
### Critical
| ID | Category | Item | Detail | Evidence |
| --- | --- | --- | --- | --- |
| A1 | Category A | <item text> | <the sites from `detail`> | <the evidence> |

### High
...

### Medium
...

### Low
...


## Unevaluated items
<any 'n/a' item with the reason from its evidence, or "none". If the run failed verification, name
the IDs here and label the run FAILED.>
```

Every verdict's evidence must state what was examined. An empty population is a legitimate `n/a` —
do not widen it to produce a finding. Do not add items, categories, or judgments beyond `checklist_items.json`.

## Maintaining the verifier

`verify_results.py` has its own tests. Run them after changing it:

```shell
uv run --no-project "<skill-dir>/verify_results_test.py"
```
