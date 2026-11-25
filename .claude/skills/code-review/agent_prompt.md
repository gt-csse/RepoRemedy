# Batch Agent Prompt Template

The parent fills every `{{…}}` placeholder and passes the result as the `prompt` to one `Agent` call
— one per batch in `checklist_items.json`, all launched in a single message.

---

You are evaluating a fixed set of checklist items against a set of code changes. Other agents own
the other items. Evaluate only the items below, and evaluate **every one of them**.

## Your items

Batch `{{BATCH_ID}}` — {{CATEGORY}}

{{ITEMS}}

## Change under evaluation

- **Scope:** {{SCOPE}}
- **Command that reproduces the diff:** `{{DIFF_COMMAND}}`
- **Files changed:** {{FILES}}

Re-run the diff command yourself. Do not evaluate from a description of the change.

## Method

For each item, in order:

1. **Enumerate the item's population and count it.** The population is stated with the item. An
   empty population is a legitimate result — verdict `n/a` with the reason. Do not widen it.
2. **Examine every member of the population**, not a sample.
3. **Record the verdict with its evidence**: the command you ran and its output, or the specific
   lines you read.

Work item by item. Each item gets its own examination, even where two items share a population.

## Output

Write a JSON array to `{{RESULTS_PATH}}` with **exactly one object per item assigned to you**, in
the order listed:

```json
[
  {
    "id": "<item ID exactly as given above>",
    "verdict": "pass | fail | n/a",
    "population_size": <integer>,
    "evidence": "<what you examined and what you observed>",
    "detail": "<optional: for a 'fail', the specific sites as path:line>"
  }
]
```

A verifier reads this file and enforces: `id` matches an assigned ID exactly; `verdict` is exactly
one of `pass`, `fail`, `n/a`; `population_size` is a non-negative integer — the count you actually
enumerated; `evidence` is a non-empty string describing what you observed, not what you expected.

Do not add a severity to your records. Severity is a fixed property of each item, and the parent
reads it from the item list.

Omitting an item is not an option. If you could not evaluate one, write its record with verdict
`n/a` and the reason in `evidence` — a missing record is a hole the verifier attributes to your
batch by ID.

Then reply with a single line: `Batch {{BATCH_ID}}: wrote N records to <path>`. Do not restate the
results — the file is the result.
