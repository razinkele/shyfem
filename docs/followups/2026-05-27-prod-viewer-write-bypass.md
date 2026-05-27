# Follow-up: Editor-role write guards are bypassed in the production WebSocket context

**Severity:** High (privilege escalation — `viewer` can perform `editor` writes in the deployed app).

**Origin:** 2026-05-27 multi-angle review of `docs/superpowers/plans/2026-05-27-deferred-issues-master-plan.md` (Phase H). Surfaced while assessing whether the planned behavioral access-control tests actually prove the guards work. They do not — and the review found the guards are inert in production.

**Problem.** The nine editor-gated write handlers guard with the pattern:

```python
user = get_current_user()
if user is not None and check_project_access(proj["id"], user, min_role="editor") is None:
    ui.notification_show("Permission denied: editor role required …", type="error")
    return
```

Because the condition is `user is not None AND <denied>`, the guard **short-circuits to ALLOW whenever `user is None`** — it only ever denies a *known* non-editor.

In the `laguna.ku.lt` deployment, `get_current_user()` returns `None` inside reactive handlers:

- The app runs behind Shiny Server with `SHYFEM_UI_ROOT_PATH=/shyfem-ui` (so `root_path` is truthy).
- Shiny Server's internal WebSocket connects from `127.0.0.1` and **does not forward the session cookie** (this is the documented reason for the WS-auth exception, commit `8e1f254`).
- `SessionAuthMiddleware` therefore admits the WS with `user=None`: `session_auth.py:613-616` —
  `if not (self.root_path and is_local): close(4001)` — with `root_path` set and a localhost client, the connection is **allowed** and `_user_var.set(None)`.
- All reactive write handlers run in that WS scope, so `get_current_user()` is `None`, and every guard above short-circuits.

**Net effect.** Any authenticated user (including one granted only `viewer` permission on a shared project) can perform editor-gated writes on that project in production: submit/cancel jobs, delete and upload files, save `.str`/physics edits, and run `shypre`/`shyparts`/`shyelab`.

**Affected handlers (all short-circuit on `user=None`):**

| Page | Handler | approx. line |
|---|---|---|
| run.py | `_submit_job` | 592 |
| files.py | `_handle_upload` | 303 |
| files.py | `_do_delete` | 433 |
| partitioning.py | `_run_shyparts` | 243 |
| grid_prep.py | `_run_shypre` | 283 |
| ensemble.py | `_submit_ensemble` | 514 |
| simulation.py | `_confirm_save` | 350 |
| physics.py | `save_file` | 448 |
| postprocess.py | `_run_shyelab` | 498 |

8 of the 9 have no other guard. `run.py:_submit_job` has a second `user_role()` guard, but it blocks only `ROLE_TUTORIAL`, **not** `viewer` — so the viewer-write bypass applies there too.

**Why the existing/planned tests miss it.** The test auth server is mounted with `root_path=""` (`tests/_test_auth_app.py:39`). With `root_path` falsy, the WS-admit-`None` branch is inactive, the browser's WS carries the cookie, and `get_current_user()` returns the real user — so the guards fire and a "viewer is denied" test passes. **The tests validate exactly the configuration where the guards work, and never exercise the production configuration where they don't.**

**Recommended fix.** Do not depend on `get_current_user()` inside reactive handlers. The app already carries a WS-safe role signal — `input.current_user_role()`, set via `Shiny.setInputValue` (see `app.py`) and already used for tutorial guards. Options:

1. **(preferred)** Make the nine guards check the WS-safe role/permission signal (resolve the user/role from `input.current_user_role()` plus the active project's permission), so the check does not rely on the cookie-less WS scope. Keep `check_project_access` for the permission logic, but feed it an identity that is actually populated in the WS context.
2. Alternatively, pass the authenticated user/role explicitly into each page's `*_server(...)` at mount time (the HTTP request scope *does* have the user), and have handlers use that rather than re-resolving per call.

Do **not** "fix" this by removing the `session_auth.py` WS exception — that exception exists because Shiny Server's internal WS legitimately has no cookie; removing it breaks the deployment (commit `8e1f254`). The fix belongs at the guard layer.

**Validation.** After fixing, add a `root_path`-set auth-server test variant (Phase H, Task H0) that reproduces the production WS-admit-`None` path and asserts a viewer is denied each write. A failing test against that config IS the bug; do not weaken the assertion to make it green.

**Related code:**
- `shyfem-ui/shyfem_ui/middleware/session_auth.py:604-625` (WS auth, the `user=None` admit branch)
- `shyfem-ui/shyfem_ui/pages/run.py:586-596`, `files.py:428-436`, and the other handlers above
- `shyfem-ui/shyfem_ui/services/access_control.py` (`check_project_access`)
- `shyfem-ui/tests/_test_auth_app.py:39` (`root_path=""` — why tests don't catch it)
