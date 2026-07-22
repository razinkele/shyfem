# F14 — network confinement of the shyfem-ui app: closure + runbook

**Status: OPERATIONAL FIX ALREADY IN PLACE (verified 2026-07-22 on laguna).**
Prepared 2026-07-22. Closes the operational half of F14; the optional
code-side defense-in-depth remains a deferred nice-to-have.

## Background

F14 (`docs/followups/2026-05-27-prod-viewer-write-bypass.md`) found that the
WebSocket-auth branch fails open behind Shiny Server: the proxy strips the
query string and presents no credential on the internal loopback WS, so a
`_wsauth`-less connection is allowed and `current_user()` resolves to `None`.
The 2026-07-19 investigation concluded this is **not exploitable for authz** —
every app-layer write gate is fail-closed on `user=None` in server mode — and
that the real fix is **operational: ensure only Shiny Server can reach the
app, so no attacker can open a raw WS to it in the first place.**

## Verification (laguna, 2026-07-22) — confinement is already satisfied

```
$ ss -ltn | grep 3838
LISTEN 0  511  127.0.0.1:3838  0.0.0.0:*      # Shiny Server: LOOPBACK ONLY
```

1. **Shiny Server binds `127.0.0.1:3838`** — not reachable from the network.
2. **The shyfem-ui worker opens no TCP port at all.** Shiny Server spawns it as
   a `su --login` subprocess and talks to it over SockJS **pipes**
   (`SockJSAdapter.py`), so there is no app socket to firewall or reach.
3. **The only externally-reachable surface is nginx (443)**, which terminates
   TLS and `proxy_pass`es to the loopback Shiny Server.
4. **No `0.0.0.0` bind belongs to shyfem** — a full `ss -ltn` shows only
   unrelated services (Dropbox LAN sync :17500, etc.) on wildcard addresses.
5. The config default is already loopback: `config.py:28`
   `host: str = Field(default="127.0.0.1")`.

So the attack the F14 fail-open would enable (a raw WS from off-box) is
**structurally impossible in the current deployment** — there is no app port to
connect to, and Shiny Server's own port is loopback-bound.

## What must stay true (deploy checklist)

Re-run after any change to the deployment model, `.env`, or systemd unit:

```bash
# 1. Shiny Server must stay loopback-bound:
ss -ltn | grep 3838            # expect 127.0.0.1:3838, never 0.0.0.0:3838

# 2. No shyfem-ui app port on a wildcard address:
ss -ltnp | grep -i python | grep -vE '127\.0\.0\.1|\[::1\]'   # expect empty

# 3. The app must NOT be launched with a wildcard host. NEVER set
#    SHYFEM_UI_HOST=0.0.0.0 in shyfem-ui/.env on a public box; the
#    default (127.0.0.1) is correct for the Shiny Server deployment.
grep SHYFEM_UI_HOST shyfem-ui/.env 2>/dev/null   # expect unset or 127.0.0.1
```

If the app is ever run standalone (e.g. `shiny run`/`uvicorn` directly, bypassing
Shiny Server) it MUST bind loopback and sit behind the same nginx, OR the WS
fail-open becomes reachable. In that case add a host firewall rule allowing the
app port only from localhost.

## Residual code-side item (deferred, optional)

Defense-in-depth only, not required given the confinement above: an app-layer
**idle-unauthenticated-WS timeout** that closes a WS which never presents a
valid `_wsauth` within N seconds. This would harden a hypothetical
mis-deployment (app bound to a public interface) without relying on the network
layer. Low priority — the authz gates already fail closed, and the network is
confined. Track here; implement only if a standalone deployment is ever wanted.

## Verdict

**Operational fix: DONE / verified.** The production deployment on laguna
confines the app exactly as F14 requires — Shiny Server loopback + pipe-based
worker + nginx-only ingress. No action needed unless the deployment model
changes; the checklist above guards that. The code-side idle-WS timeout stays
deferred as optional hardening.
