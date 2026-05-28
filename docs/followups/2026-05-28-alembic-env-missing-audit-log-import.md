# Follow-up: `migrations/env.py` does not import `audit_log`, so autogenerate proposes to drop `audit_logs`

> **Resolved 2026-05-28** on branch `fix/alembic-env-import-audit-log`. Fixed by adding explicit `audit_log` + `user` imports to `migrations/env.py`, with a new `tests/test_migrations_env.py` guard that fails if any model submodule under `shyfem_ui/models/` is missing from env.py's import list. Mutation-verified: backing the `audit_log` import out makes both guard tests fail with a clear, actionable message. Empty-autogenerate check confirms no spurious DDL is proposed.

**Severity:** High (any next `alembic revision --autogenerate` run, on any branch, will produce a migration that silently drops the live `audit_logs` table and all audit history with it).

**Origin:** 2026-05-28, Task 1.1 of `docs/superpowers/plans/2026-05-28-ws-trusted-identity.md`. Running `alembic revision --autogenerate -m "ws_auth_tokens"` for the new `WSAuthToken` model produced — alongside the expected `ws_auth_tokens` `create_table` — an unrequested `drop_table('audit_logs')` plus three `drop_index` calls. Stripped from the committed migration (`f640c55`); the trap remains in `env.py`.

## Problem

`shyfem-ui/migrations/env.py` only imports two model modules:

```python
from shyfem_ui.models import project   # noqa: F401
from shyfem_ui.models import workflow  # noqa: F401
```

Other model modules get into `Base.metadata` only by accident, via `relationship()` / `ForeignKey("users.id")` references inside `project.py` that force SQLAlchemy to resolve and import them at class-definition time. That accident covers `user.py` (and its `User` / `AuthSession` / `ProjectPermission` / `WSAuthToken` classes) because `Project` and `Job` both `ForeignKey("users.id")`. It does **not** cover `audit_log.py`: nothing in `project.py` or `workflow.py` references `AuditLog`, so the class is never loaded and the `audit_logs` table is never in `Base.metadata`.

Alembic's autogenerate compares `Base.metadata` to the live DB, sees the table in the DB without a metadata match, and proposes to drop it. Verified at the Python REPL: importing only `project` + `workflow` yields metadata containing every table the project has *except* `audit_logs`.

## Why this is dangerous now

- Every Alembic autogenerate run on any branch will reproduce this. The next developer to add a model — or even add a column to an existing one — gets a migration that drops `audit_logs` mixed in with their real change.
- The drop is easy to miss in review: it's in the same generated file, in the same diff hunk style, with the same Alembic boilerplate.
- Applying such a migration to production deletes all audit history. SQLite has no per-row delete audit; the rows are gone.
- The current `f640c55` migration only ducked it because Task 1.1 caught the spurious DDL in the autogenerate output and stripped it by hand.

## Suggested fix

Add the missing import in `shyfem-ui/migrations/env.py`, alongside the existing `project` / `workflow`:

```python
from shyfem_ui.models import audit_log  # noqa: F401  -- register AuditLog for autogenerate
from shyfem_ui.models import user       # noqa: F401  -- register User/AuthSession/WSAuthToken explicitly
```

Adding `user` is belt-and-braces — today it's pulled in transitively by `project`'s FK to `users.id`, but that's a fragile invariant to lean on, and the next refactor that removes a relationship could re-open the same trap for the user tables.

Then run autogenerate against the current DB state with **no model changes** and confirm the output is an empty migration:

```bash
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m alembic revision --autogenerate -m "no-op verify"
# Expect: an empty upgrade()/downgrade(); delete the generated file.
```

Optional hardening: add a tiny test that imports `migrations.env` and asserts `'audit_logs' in Base.metadata.tables` (or that every `__tablename__` reachable from `shyfem_ui.models.*` modules is in `Base.metadata` after env.py runs), so the trap can't quietly reopen.

## Related code

- `shyfem-ui/migrations/env.py:22-24` (the incomplete import list)
- `shyfem-ui/shyfem_ui/models/audit_log.py:11` (the orphaned model)
- `shyfem-ui/shyfem_ui/services/audit_service.py:38` (the live consumer — proves the model is in use, not dead code)
- `shyfem-ui/migrations/versions/f423af2c2f44_add_audit_logs_table.py` (the migration that originally created the table; confirms it's tracked)
- `shyfem-ui/migrations/versions/43b512fc310e_ws_auth_tokens.py` (commit `f640c55`; the migration where the spurious drop was caught and stripped)
