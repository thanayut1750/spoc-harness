# Project instructions

## Investigating issues and fixing bugs

For every new issue or bug found in this project:

- Search the entire codebase for the same underlying failure pattern. Inspect shared helpers, callers, analogous implementations, and relevant boundaries across workers, subagents, graph orchestration, providers, persistence, API, CLI, and UI.
- Fix every affected occurrence within the authorized scope. Preserve unrelated user changes and keep changes focused on the underlying cause.
- Add meaningful regression coverage for the reported failure and other affected paths or boundary cases where appropriate. Tests should verify observable behavior.
- Run the relevant checks, including broader checks when shared behavior changes, before declaring the issue fixed.
- Report the root cause, the scope of the codebase check, related occurrences addressed, and verification results. State any remaining gaps clearly.

Apply this rule to future fixes as a standing user preference.
