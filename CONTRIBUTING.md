# Contributing

1. Create a descriptive branch from `main` (for example, `codex/fix-checkpoint-resume`).
2. Keep changes focused and document behavior changes and migrations.
3. Add tests for meaningful behavior and regression cases. Offline tests must not consume live API quota.
4. Run `uv run ruff check .`, `uv run pytest -m 'not live'`, and frontend `check`, `test`, `build`, and `e2e` scripts.
5. Open a pull request describing the problem, resulting behavior, validation, and any unverified integration.
6. Resolve review feedback and required CI checks before merging. Do not bypass branch protection or commit secrets.

Use the committed lockfiles for reproducible dependencies. A schema change needs an explicit, compatible migration and restart/recovery coverage. Avoid broad exception handlers that hide programming errors; redact provider bodies and credentials from user-facing failures.
