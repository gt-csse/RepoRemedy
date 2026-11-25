---
name: prepare-pr
description: Prepare the current git branch for a future pull request by creating a branch off mainline if needed, generating an OKF file, committing outstanding changes, squashing all branch commits into one, writing a commit message in the `commit_emojis` format, and pushing to origin. Use when the user asks to prepare a branch/PR, squash and push, wrap up a branch, or get changes ready for review.
metadata:
    version: 0.1.0
---

# Prepare Branch for PR

Collapse the current branch's work into a single well-described commit on a non-mainline branch and push it to `origin`, ready for a PR.

## Preconditions

Verify before doing anything else. Stop and report if any fail.

- Inside a git work tree.
- No rebase/merge/cherry-pick in progress (`.git/rebase-merge`, `.git/rebase-apply`, `.git/MERGE_HEAD` absent).
- `origin` remote exists.
- `commit_emojis` is available. Resolve the invocation in this order and use the first that works:
  1. `uv run commit_emojis` — installed as a dev dependency of the current project (`uv run commit_emojis --help` succeeds).
  2. `commit_emojis` — on `PATH` (`commit_emojis --help`).

  The resolved command is referred to as `<commit_emojis>` in the rest of the skill. If neither works, error out — do not substitute `uvx`, a hardcoded emoji list, or any other method.

## Step 1 — Gather state

```bash
git rev-parse --abbrev-ref HEAD          # current branch
git remote show origin | grep 'HEAD branch'   # mainline branch name
git status --porcelain                   # outstanding changes
```

Determine the mainline branch from `origin`'s HEAD. Fall back to whichever of `main` or `master` exists locally. Do not assume `main`.

Detached HEAD is a hard stop — ask the user how to proceed.

## Step 2 - Slugify

Analyze the outstanding changes and generate a slug that captures the essence of the change (e.g. `add-json-output`, `fix-encoding-error`) - lowercase, hyphen-separated, no emoji or type prefix.

This value will be referred to as `<slug>` in the rest of the skill.

## Step 3 — Branch if on mainline

If the current branch is mainline, create and switch to a new branch named `<slug>`. If already on a non-mainline branch, keep it.

## Step 4 - Describe the change

It is important to preserve what was changed and why the change was made. Write `docs/changes/<datetime>_<slug>.md` according to the [Open Knowledge Foundation (OKF) change file format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf). Attempt to derive all necessary information from information in the source code, but interview the user through no more than five questions if additional information is needed. Favor compliance with the OKF format over conformance to existing change files.

Commit this change if the working tree is clean. If there are outstanding changes, skip the commit as they will be squashed in later steps.

## Step 5 — Establish the squash base

The base is the merge-base with mainline:

```bash
git merge-base HEAD <mainline>
```

Count the commits to be squashed with `git rev-list --count <base>..HEAD`.

If the base equals `HEAD` and there are no outstanding changes, there is nothing to prepare — report that and stop.

## Step 6 — Compose the commit message

Derive the commit message based on the information gathered in Step 4. The message must be in the `commit_emojis` format, which is a subject line with an optional body. The subject line must start with an emoji and an alias in square brackets, followed by a concise summary of the change. The summary should include one paragraph of 2-3 sentences describing what changed. The second paragraph should explain why the change was made.

### Read the emoji vocabulary at runtime

Never rely on a memorized emoji list; it changes as `commit_emojis` is updated. Always query it fresh:

```bash
PYTHONIOENCODING=utf-8 <commit_emojis> DisplayJson
```

`PYTHONIOENCODING=utf-8` is required — the tool crashes with a `UnicodeEncodeError` when stdout uses a legacy codepage (common on Windows).

The output is a JSON array of categories:

```json
[
  {
    "category": "Functionality",
    "items": [
      {
        "name": "sparkles",
        "emoji": "✨",
        "code": ":sparkles:",
        "description": "Introduce new features.",
        "aliases": ["+feature", "added_feature"]
      }
    ]
  }
]
```

Select the entry whose `description` best matches the change, then pick the alias verbatim from that entry's `aliases` list. A `category` of `"Intentionally Skipped"` marks entries not to use.

Copy aliases exactly — never construct one by analogy. The `+`/`-` prefixes describe what the *change* does to the named thing, which is not always intuitive: fixing a bug is `-bug` (a bug is removed), not `+bug`. `:+bug:` is not a valid alias and passes through untransformed.

### Build the subject

Write the raw subject using the chosen alias in colon-delimited form:

```
:<alias>: <imperative-past summary of the change>
```

`Transform` converts that into the final committed form:

```
<emoji> [<alias>] <summary>
```

Worked example — raw subject written to the message file:

```
:+feature: Added functionality to display JSON and version
```

after `Transform`, which is what actually gets committed:

```
✨ [+feature] Added functionality to display JSON and version
```

Note the emoji and the square brackets are produced by `Transform`. Never type them by hand — write only the `:<alias>:` form and let the tool substitute.

Match the repository's existing style by inspecting `git log --format=%s -20`. Keep the summary concise — roughly 50-72 characters after transformation.

#### Multiple entries

A subject may carry more than one entry by leading with several aliases, which `Transform` substitutes in order:

```
:+feature: :+test: Added JSON output and covering tests
```

```
✨ [+feature] ✅ [+test] Added JSON output and covering tests
```

**Default to a single entry.** Use multiple only when absolutely necessary — when the change genuinely has two co-equal purposes that a reader would misjudge if either were omitted. Prefer one entry naming the dominant purpose, with the rest explained in the body.

Adding tests or docs alongside a feature is *not* sufficient reason; that is normal, expected work and belongs under the single `:+feature:` entry. Squashed branches make this trap likely, since one commit now spans everything the branch touched. Ask whether a second entry changes how the commit is understood, not merely whether a second kind of file was touched.

Each additional entry dilutes the subject and consumes characters, so keep the total to two if one truly will not do. Three or more is effectively never right — that signals the branch should be several commits, or the summary is too broad.

### Transform

Write the full message (subject, blank line, body) to a temp file, then let `commit_emojis` substitute the emoji:

```bash
PYTHONIOENCODING=utf-8 <commit_emojis> Transform <message-file>
```

`Transform` rewrites `:alias:` tokens and passes the rest through unchanged, so the body is safe to include. Capture the transformed output — that is the final commit message. Verify the subject now starts with an emoji followed by `[<alias>]`; if the alias survived untransformed, it was not a valid alias, so re-select from the JSON.

## Step 7 — Present the plan and get approval

Squashing rewrites history and pushing is outward-facing, so **always** confirm before acting. Show:

- Current branch → target branch (note if a new branch will be created).
- Mainline branch and squash base.
- Number of commits being squashed and count of outstanding changed files.
- The final transformed commit message, verbatim.
- Whether the push will be a normal push or require a force-push.
- If the subject carries more than one entry, why a single entry was insufficient.

Wait for explicit approval. If the user revises the message, re-run `Transform` on the revision rather than hand-editing the emoji.

## Step 8 — Execute

1. Create/switch the branch if Step 2 called for it.
2. Stage everything: `git add -A`.
3. Soft-reset to the base so all branch commits plus the working tree become one staged change set: `git reset --soft <base>`.
4. Commit from a file to preserve the message exactly: `git commit --file <message-file>`.

Use `--file`, not `-m`, so multi-line bodies and emoji survive shell quoting.

Skip the reset when the base is already `HEAD` (only uncommitted work exists) — just commit.

## Step 9 — Push

Try the normal push first:

```bash
git push --set-upstream origin <branch>
```

If it is rejected as non-fast-forward, the branch was already pushed and the squash rewrote its history. **Stop and ask the user** whether to force-push; do not force-push unprompted. On approval:

```bash
git push --force-with-lease origin <branch>
```

Use `--force-with-lease`, never bare `--force`, so the push aborts if `origin` received commits that are not reflected locally.

## Step 10 — Report

State the branch name, the final commit subject, and the push result. Include the PR-creation URL if `git push` emitted one. Do not open the PR — this skill only prepares the branch.

## Failure handling

- **Pre-commit hooks modify files or fail** — report the hook output and stop. Do not `--no-verify`.
- **Nothing staged after reset** — the branch had no net change against mainline; report and stop without committing.
- **Merge conflicts** — cannot occur with `reset --soft`; if one appears, a different operation is in progress. Stop and report.

The history rewrite is recoverable via the reflog. If the user needs to undo a squash, `git reset --hard <original-HEAD-sha>` restores it — capture that SHA before Step 6 and include it in the Step 8 report.
