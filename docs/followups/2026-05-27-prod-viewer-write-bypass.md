# Follow-up: Project access control is unenforced in the production reactive layer

> **Status: RESOLVED (2026-05-31).** Fixed on `feat/ws-auth-phase3b`
> (commits `fd8a1ef`..`2fb5e45`). WS identity now flows through
> `Shiny.setInputValue('_wsauth')` → `resolve_ws_user()` → `current_user()`,
> and a fail-CLOSED `services/access_control.editor_denied_reason` gate (deny on
> `user is None` in server mode; allow in local desktop mode) replaces the
> fail-open `if user is not None and …` shape across all 14 write/read handlers
> plus `load_project_context` (activation/clone/export). Verified by unit tests,
> a static-AST guard-enforcement harness (asserts all 14 handlers call the gate
> *and* act on its verdict), and a Playwright direct-WS bypass test.
>
> **Remaining (pre-existing, out of this fix's 9-handler scope — tracked):**
> the **admin panel** still gates on the spoofable `input.current_user_role()`
> signal (`admin_server` not threaded `current_user`); `mesh_builder` save is
> unguarded; the dashboard transiently lists all projects unfiltered before
> `_wsauth` resolves; and create/clone/import can stamp `owner_id=None` if
> identity is unresolved.

**Severity:** High (multi-user isolation failure — in the deployed app any authenticated user can view, open, and edit projects they were never granted access to; the editor-write bypass is one facet). Requires an authenticated account (not anonymous), which is the main mitigating factor.

> **Scope note:** originally filed as a "viewer-write bypass," investigation on 2026-05-27 found the root cause is singular and broader — `get_current_user()` is `None` across the whole reactive layer in production, so read-listing, project activation, AND the 9 write guards all fail open. The naive fixes (`input.current_user_role()`, "pass user at mount") are insecure or non-functional; see the fix section.

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

**Broader than the write guards (2026-05-27 deeper trace — the root cause is singular).** Because `get_current_user()` returns `None` across the *entire* reactive/WS layer in production, ALL identity-dependent authorization in the reactive UI fails open, not just the 9 write guards:

1. **Read isolation is gone.** `home.py:_refresh_projects` (281-286): `user = get_current_user()` is `None`, so `if user and user.get("role") != ROLE_ADMIN` is False and it falls into the `else` branch — `db.query(Project)…limit(10)` — listing every user's recent projects.
2. **Activation is unguarded.** `home.py:_activate_project` (661) calls `load_project_context(project_id, user=_current_user)`, and `_current_user` is captured at server-body time (`home.py:253`, in the WS scope) so it is `None`; `load_project_context` then *skips the viewer access check* (`project_context.py:54-60` — "skip when user is None — local mode") and returns any project. A user can open any `project_id`.
3. **Writes are unguarded** — the 9 editor guards above.

So project-level multi-user isolation is effectively non-functional in the deployed app: an authenticated account can see, open, and edit projects it was never granted access to. The HTTP login still gates *who can use the app at all*, but once in, per-project ownership/permission is not enforced in the reactive layer.

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

**The naive fixes do not work — and one is itself insecure.** Two obvious-looking fixes must be rejected:

- ❌ **"Use `input.current_user_role()` in the guards."** That signal is set by the **client**: the browser fetches `api/whoami` over HTTP (where the cookie works) and pushes the role in via `Shiny.setInputValue('current_user_role', data.role)` (`app.py:422-428`). A malicious authenticated user can run `Shiny.setInputValue('current_user_role','admin')` from the console and elevate. It is acceptable for cosmetic hiding and the honest-user tutorial guard, but it **cannot be an authorization boundary.** It also carries only the *account* role (`admin/user/tutorial`), not the *project* permission (`owner/editor/viewer`) these guards need.
- ❌ **"Pass the authenticated user into each `*_server(...)` at mount time."** The page/app server function runs **over the WebSocket**, not in the HTTP scope — that is the whole bug. There is no HTTP-scope user available at mount.

**The fix is architectural: establish trusted, server-side identity in the Shiny session behind the proxy.** Candidate approaches (decision needed — this is a security design choice for the project owner):

1. **Server-issued, server-validated session token.** On HTTP login, mint a per-session random token bound server-side to the `user_id` (stored in the existing session table). Expose it to the authenticated browser via the cookie-authenticated `whoami` endpoint, and have the browser hand it to the Shiny session (WS query param or `setInputValue`). The server resolves identity by **looking the token up in its own store** — not by trusting a client-sent role — so it is not spoofable. All reactive guards then resolve the real `user_id`/project permission from the validated token. Robust, but the most work.
2. **Make the cookie reach the app's WebSocket (deployment change).** Investigate whether Shiny Server / nginx can forward the session cookie (or the app can be served so the WS carries it), so `get_current_user()` works natively in the reactive layer and the existing guards/`load_project_context` checks just start working. Likely the smallest *code* change, but it touches the **laguna.ku.lt production deployment** — per `CLAUDE.md`, confirm before modifying, and re-verify the original reason the WS exception was added (commit `8e1f254`).
3. **Defense-in-depth at the service layer.** Enforce ownership/permission inside the write services (FileService delete/upload, job submit, etc.) — but this still needs trusted identity at that layer, so it depends on (1) or (2) and is a complement, not a substitute.

Do **not** "fix" this by simply removing the `session_auth.py:613-616` WS exception — it exists because Shiny Server's internal WS legitimately has no cookie; removing it would close the WS for everyone (commit `8e1f254`).

**Validation.** After fixing, add a `root_path`-set auth-server test variant (Phase H, Task H0) that reproduces the production WS-admit-`None` path and asserts a viewer is denied each write. A failing test against that config IS the bug; do not weaken the assertion to make it green.

**Related code:**
- `shyfem-ui/shyfem_ui/middleware/session_auth.py:604-625` (WS auth, the `user=None` admit branch)
- `shyfem-ui/shyfem_ui/pages/run.py:586-596`, `files.py:428-436`, and the other handlers above
- `shyfem-ui/shyfem_ui/services/access_control.py` (`check_project_access`)
- `shyfem-ui/tests/_test_auth_app.py:39` (`root_path=""` — why tests don't catch it)
