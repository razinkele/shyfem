# Design: Trusted server-side identity in the Shiny WebSocket layer

**Date:** 2026-05-28
**Status:** Design — approved in brainstorming, pending spec review → implementation plan
**Origin:** `docs/followups/2026-05-27-prod-viewer-write-bypass.md` (High-severity production access-control gap)

## Problem

In the `laguna.ku.lt` deployment, `get_current_user()` returns `None` across the **entire** Shiny reactive/WebSocket layer. Root cause: Shiny Server's internal WebSocket connects to the app from `127.0.0.1` **without the browser's session cookie**, and `SessionAuthMiddleware`'s WS branch (`session_auth.py:613-616`) admits that connection with `user=None`. Because every reactive authorization decision depends on `get_current_user()`, all of them fail open:

1. **Read isolation** — `home.py:_refresh_projects` (281-286) falls into the all-projects branch → every user sees others' projects.
2. **Activation** — `home.py:_activate_project` (661) calls `load_project_context(project_id, user=None)`, which *skips* the viewer access check (`project_context.py:54-60`) → any user can open any project.
3. **Writes** — the 9 editor guards (`run.py:590-592`, `files.py:432-433`, etc.) are `if user is not None and check_project_access(...) is None: deny` and short-circuit to ALLOW when `user is None`.

The only existing identity bridge, `input.current_user_role()`, is **client-pushed via `Shiny.setInputValue`** (`app.py:422-428`) and therefore spoofable — unusable as an authorization boundary — and carries only the account role, not the project permission.

## Goal / Non-goals

**Goal:** Establish trusted, server-validated user identity in the Shiny WebSocket scope so that `get_current_user()` returns the real user in reactive handlers, restoring correct per-project access control with **no rewiring of downstream consumers**.

**Non-goals:**
- No change to the `laguna.ku.lt` deployment configuration (nginx / Shiny Server). Code-only fix.
- No new authentication system — reuse the existing `AuthSession` table and `AuthService` token patterns.
- Not addressing the unrelated partition `.par` format bug (`docs/followups/2026-05-27-shyparts-output-format-mismatch.md`).

## Threat model

**Malicious authenticated user**, pragmatically scoped. Assume a logged-in user may try to escalate (spoof identity, replay/forge a token, open another user's project). The identity token must be server-issued, server-validated (lookup → real `user_id`), session-bound, and expire with the session. We do **not** add rotating-nonce / per-message crypto — reusing the session-token infrastructure is sufficient. Anonymous (pre-login) access is already gated by the HTTP login layer and is out of scope.

## Architecture & data flow

```
1. Browser logs in over HTTP            → session cookie set (httponly, unchanged).
2. On page load, JS calls fetch('api/whoami')  (cookie-authenticated).
   whoami ALSO returns a server-issued WS-auth token bound to the user_id.
3. JS attaches the token to Shiny's WebSocket URL as ?_wsauth=<token>
   BEFORE the socket opens.
4. SessionAuthMiddleware (WS branch) reads scope["query_string"],
   validates the token server-side (lookup → user_id), and sets
   _user_var to the REAL user instead of None.
5. Every reactive handler now sees get_current_user() == the real user:
   the 9 write guards, load_project_context, _refresh_projects all
   enforce correctly with ZERO downstream changes.
```

**Design principle:** fix at the root (the one middleware branch that sets `user=None`), leaving all already-correct downstream code untouched.

## Component 1 — The WS-auth token

A **distinct, server-issued, session-lived** token (not the HTTP cookie value).

- **Mint:** `AuthService.create_ws_token(user_id) -> str` — generates `secrets.token_hex(32)`, stores a row (reuse the `auth_sessions` table with a `kind="ws"` discriminator column, or a sibling table — to be pinned in the plan against the live schema) bound to `user_id`, with `expires_at` matching the owning session's lifetime.
- **Validate:** `AuthService.validate_ws_token(token) -> dict | None` — returns the user dict if the token exists and is unexpired, else `None`. Mirrors `validate_session`.
- **Lifecycle:** invalidated when the session ends (logout / session expiry / `cleanup_expired_sessions`). Reuse the existing cleanup path.

**Lifetime decision — session-lived, NOT single-use.** Shiny-for-Python re-opens the WebSocket on any network blip, reusing the same URL. A single-use or short-TTL token would fail every reconnect and silently log the user out. Session-lived is therefore required. Distinctness from the cookie limits blast radius: a leaked WS token grants only *WebSocket identity*, not HTTP/cookie actions, and dies with the session.

**Residual risk + mitigation.** A token in a URL can land in `nginx` / Shiny Server access logs. Mitigation: (a) configure the access-log format to strip the `_wsauth` query parameter; (b) the token only establishes *identity* — every permission decision remains a server-side check by the existing guards. If putting any token in a URL is unacceptable, that forces the Approach 2 transport (below).

## Component 2 — Transport & the feasibility spike

The browser must attach `?_wsauth=<token>` to Shiny's client WebSocket URL before it opens. Shiny owns that URL, so the exact hook (a global/config the client reads, or wrapping the connection) is determined by the spike.

**Feasibility spike (FIRST implementation milestone — Approach 1 is unproven until it passes):**
1. **Local:** confirm JS can attach the param and the middleware reads it from `scope["query_string"]`. (Proves the client half only — no proxy in front.)
2. **Behind Shiny Server (the decisive check):** confirm the query string survives the Shiny Server → app internal-WS hop (the same hop that strips the cookie). **Requires a Shiny-Server-backed environment** (local Shiny Server install or staging/laguna) — cannot be validated on a bare dev box.
3. **Reconnect:** confirm Shiny's auto-reconnect reuses the URL with the param intact, and that Shiny Server does not open its own token-less internal WS that the new middleware would wrongly close.

**Approach 2 — fallback if any spike part fails.** Token via `Shiny.setInputValue('_wsauth', …)`; a session-scoped reactive resolves `user_id = validate_ws_token(input._wsauth())` once, server-side; the 9 guards + activation + listing are rewired to read that resolved identity. Reliable transport, larger blast radius. The implementation plan branches here based on the spike outcome.

## Component 3 — Enforcement (middleware) & local-mode preservation

- **Single change** in `SessionAuthMiddleware`'s WS branch: when the cookie yields no user, read+validate `_wsauth`; on success set `_user_var` to the real user.
- **Server mode, token-less or invalid → close (4001).** Admitting `None` is the bug, so behind the proxy a valid token is *required* to establish identity. Legit clients always attach it before connecting; a first-connect race resolves on reconnect.
- **Local/unauth mode untouched.** When `root_path` is empty (local dev, `_test_app.py`, current `_test_auth_app.py`), no token is expected and `user=None` keeps meaning "local mode — full access." The bridge activates only in server mode, keeping the existing suite green.
- **Defense-in-depth:** keep the existing `is_local` structural check alongside token validation.

## Error handling

| Condition | Behavior |
|---|---|
| Server mode, valid token | `_user_var` = real user; proceed. |
| Server mode, missing/invalid/expired token | Close WS `4001`. Client re-fetches `whoami` → fresh token → reconnect. |
| Local mode (`root_path` empty), no token | `user=None` (local mode); unchanged. |
| `whoami` called without valid cookie | Return 401 (existing behavior); no WS token minted. |
| Token validation DB error | Treat as invalid (fail closed → `4001`); log at WARNING with the request id. |

## Testing strategy

- **Unit:** `create_ws_token` / `validate_ws_token` — mint, validate, expiry, unknown-token → `None`, invalidation on session end.
- **Middleware:** WS branch with (a) valid token → `_user_var` set to user; (b) invalid/missing token in server mode → `4001`; (c) local mode (`root_path=""`) → `user=None` unchanged.
- **Integration (ties into deferred Phase H, Task H0):** add a `root_path`-set auth-server test variant. Drive a viewer through the real UI and assert each of the 9 editor writes is denied *and* the mutation does not occur (out-of-band filesystem/DB check) — this is the test that proves the guards fire under prod-like config. Today, without this fix, that test FAILS (viewer can write); after the fix it passes.
- **Read/activation isolation:** assert a viewer's dashboard lists only their projects, and activating a non-shared `project_id` is refused.
- **Regression:** the full existing suite (local-mode `_test_app.py` / `_test_auth_app.py` at `root_path=""`) stays green.
- **Spike artifacts:** the feasibility-spike findings (which hook attaches the param; proxy-forwarding result; reconnect behavior) are recorded in the plan before the A1/A2 branch is chosen.

## Rollout considerations

- **Visible behavior change:** once live, laguna users see only *their* projects and the guards enforce — the current "everyone sees/edits everything" behavior stops. Notify current users who may rely on the broken-open visibility, and confirm sharing is set up where cross-access is actually intended.
- **Access-log scrubbing** of `_wsauth` must land with (or before) the feature.
- **Deploy ordering:** server-side (token mint/validate + middleware) and client-side (JS attach) ship together; a server with validation enabled but clients not yet attaching tokens would close WS connections.

## Affected files (anticipated)

- `shyfem_ui/services/auth_service.py` — `create_ws_token` / `validate_ws_token`.
- `shyfem_ui/models/user.py` — `AuthSession` `kind` column (or sibling token table) + migration.
- `shyfem_ui/middleware/session_auth.py` — WS branch token validation.
- `shyfem_ui/app.py` — `whoami` returns the WS token; JS attaches `?_wsauth=` to the Shiny WS URL.
- `tests/` — unit + middleware + a `root_path`-set integration variant.
- Deployment: access-log format (documented; applied at deploy time, not a code change).

## Open questions / risks

1. **Spike outcome** decides Approach 1 vs 2 — the single biggest risk. Mitigated by making the spike the first milestone and writing the plan to branch.
2. **Exact token storage** (reuse `auth_sessions` with `kind` vs sibling table) — pinned in the plan against the live schema + migration conventions.
3. **Shiny client WS-URL hook** — which mechanism reliably injects the query param across Shiny-for-Python's connect/reconnect, confirmed by the spike.
