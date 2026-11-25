---
type: change
title: Restart RepoRemedy from fresh scaffolding
description: Removes the prior RepoRemedy implementation, replaces it with a placeholder CLI, adds agent tooling, and hardens CI/CD.
tags: [restart, scaffolding, ci, release, agents]
status: stable
generated:
  by: claude-opus-5-5
  at: 2026-11-25T15:34:44Z
---

# Summary
The previous RepoRemedy implementation is discarded so the project can be rebuilt from scratch on new scaffolding.

# Changes

## Removed
- All prior application modules under `src/RepoRemedy` (CLI, TUI, batch, catalog, inputs, plan, propose, publication, resolve, review, workflow, repository context, templates).
- All associated tests and fixtures under `tests/`.
- `demo/` batch configuration and captured audit reports.
- `doc/` design and usage documents for the removed functionality.
- Runtime dependencies `httpx`, `pydantic`, and `textual`.
- Project-specific README content (Overview and usage now `TODO`).

## Added
- `src/RepoRemedy/__main__.py`: placeholder Typer `EntryPoint` command with `--version`, `--verbose`, and `--debug`, built on `dbrownell-common`'s `DoneManager`. The console script now targets `RepoRemedy:__main__.app`.
- `tests/__main___test.py` covering the entry point.
- `AGENTS.md` with repository conventions for coding agents.
- `.claude/skills/code-review` and `.claude/skills/prepare-pr` project skills; `.claude` is excluded from `ruff` and `ty`.
- `dbrownell-commitemojis` dev dependency for commit message formatting.
- DEVELOPMENT.md section describing semantic version increments.

## CI/CD
- `CICD.yml`: concurrency groups that cancel superseded PR runs while giving each push a unique group so no release is skipped; `python_package_version` renamed to `build_python_version`.
- `CICD_impl.yml`: job timeouts and a job-level `COVERAGE_FILE`.
- `release_impl`: inputs passed explicitly instead of via `env`; secrets passed through step `env` rather than inline interpolation; signing key written to a `RUNNER_TEMP` file removed by `trap`; tag push and release creation retried via `retry.sh`; release upload made idempotent for reruns.
- `release_sources.yaml` and `src/AutoGitSemVer.yaml` cross-reference each other so release triggers and version calculation stay aligned.

## Governance
- MAINTAINERS.md: ownership transferred from Ketan Bhardwaj to Sriram Chockalingam and David Brownell.

# Rationale
The existing implementation is being abandoned in favor of a from-scratch rebuild. Starting from minimal scaffolding avoids carrying forward modules, tests, and dependencies that the new design will not use, while the CI/CD hardening and agent tooling establish the baseline for subsequent work.
