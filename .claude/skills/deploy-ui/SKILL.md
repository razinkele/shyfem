---
name: deploy-ui
description: Deploy shyfem-ui to laguna.ku.lt safely — reload the symlinked worker, refresh editable metadata on a version bump, apply Alembic migrations with a DB backup, and verify /health reports the new version. Use when shipping UI changes to production.
disable-model-invocation: true
---

# Deploy shyfem-ui to laguna.ku.lt

Production deploy of the Shiny UI. **This affects the live prod app** — per project policy, confirm with the user before running the side-effecting steps. This skill is user-invoked (`/deploy-ui`); do not trigger it autonomously.

## Topology (why deploy is just "act locally")

`laguna.ku.lt` **is this dev box** (`hostname: laguna`). The live app directory `/srv/shiny-server/shyfem-ui` is a **symlink to the git working tree** `/home/razinka/shyfem/shyfem-ui`. So there is no copy/rsync step — updating the tree + reloading the worker *is* the deploy.

```
nginx (443) → Shiny Server (127.0.0.1:3838, node) → Python worker (runs as `shiny` user, reads .env, server mode)
```

- The worker **lazy-spawns** on the first request after a restart (~5s).
- The worker reads `shyfem-ui/.env` (server mode). systemd `Environment=` vars do NOT reach it (`su --login` strips them).

## Reload mechanisms (pick the lightest that applies)

| Mechanism | Effect | When |
|-----------|--------|------|
| `touch shyfem-ui/restart.txt` | Shiny Server respawns the Python worker on next request | Code-only change (no dependency/metadata change) |
| `sudo systemctl restart shiny-server` | Full Shiny Server restart | Rarely needed; heavier, also kills other apps |

Prefer `touch restart.txt`. `restart.txt` already exists in the tree.

## Decision: what kind of deploy is this?

1. **Code-only** (Python edits, no version bump): tree up to date → `touch restart.txt` → verify. Done.
2. **Version bump** (`shyfem-ui/pyproject.toml` changed): ALSO refresh editable metadata (below), or `/health` will keep reporting the OLD version.
3. **Schema change** (new Alembic migration): ALSO back up the DB and run `alembic upgrade` (below) BEFORE reloading.

Always do these in order: **migrate → metadata refresh → reload → verify**.

## Pre-flight checks

```bash
cd /home/razinka/shyfem
git status --short                      # tree should be the commit you intend to ship
git log --oneline -1
# Confirm the live app dir really points at this tree:
ls -l /srv/shiny-server/shyfem-ui
# What shiny version will the WORKER actually load? (user-site is disabled for the worker)
PYTHONNOUSERSITE=1 /opt/micromamba/envs/shiny/bin/python -c "import shiny; print('worker shiny', shiny.__version__)"
```

> ⚠️ **shiny version split.** The worker runs **conda shiny 1.4.0**, but the interactive/test env loads **1.6.3 from `~/.local`** (user-site shadow). CI green ≠ prod-safe. Any shiny ≥1.6-only API (e.g. `ui.update_navset`) must be guarded with a `getattr(ui, "update_navset", None) or ui.update_navs` fallback, or it crashes the WS session on the 1.4.0 worker. **Restarting the worker is what exposes latent 1.6-API crashes** (long-lived workers ran old code in memory). Grep your diff for new `ui.update_*`/1.6 APIs before deploying.

## Step 1 — Schema change only: back up DB + migrate

The prod DB is SQLite at `/home/razinka/shyfem/shyfem-ui/shyfem_ui.db` (per `.env` `SHYFEM_UI_DATABASE_URL`).

```bash
cd /home/razinka/shyfem/shyfem-ui
# Timestamped backup BEFORE any migration (never skip this):
cp shyfem_ui.db "shyfem_ui.db.bak.$(date +%Y%m%d-%H%M%S)"
# Inspect pending migrations, then apply:
/opt/micromamba/envs/shiny/bin/alembic current
/opt/micromamba/envs/shiny/bin/alembic heads
/opt/micromamba/envs/shiny/bin/alembic upgrade head
/opt/micromamba/envs/shiny/bin/alembic current   # confirm it advanced
```

> The `.db` file AND its parent dir must be writable by the `shiny` user (uid 998) — SQLite needs to create WAL/journal files. If permissions drifted: `chgrp shiny shyfem_ui.db && chmod 664 shyfem_ui.db`.

## Step 2 — Version bump only: refresh editable metadata

`shyfem_ui.__version__` derives from `importlib.metadata.version("shyfem-ui")`, which reads the cached `*.dist-info`. A `git pull`/code reload does NOT refresh it — `/health` will report the stale version until you reinstall the editable metadata.

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/pip install -e . --no-deps   # --no-deps: only refresh metadata, don't touch the conda-managed deps
```

> Do NOT drop `--no-deps`. pip-forcing conda-managed packages (shiny, shinywidgets, shiny-deckgl) corrupts the env, which is owned `shiny:micromamba`.

## Step 3 — Reload the worker

```bash
touch /home/razinka/shyfem/shyfem-ui/restart.txt
```

## Step 4 — Verify (the deploy is NOT done until this passes)

```bash
sleep 6   # let the worker lazy-spawn on first request
curl -fsS https://laguna.ku.lt/shyfem-ui/health    # or the app's health route; expect HTTP 200
# Confirm the reported version matches pyproject.toml on a version bump:
grep '^version' /home/razinka/shyfem/shyfem-ui/pyproject.toml
```

- `/health` should return **200** and the **new** version. If it 503s or shows the old version, the deploy did not fully take — re-check Step 2 (metadata) and Step 3 (restart).
- Open `https://laguna.ku.lt/shyfem-ui/` in a browser and confirm login works and no WS-disconnect-on-login (the classic shiny-version-split symptom).

## Observing failures

Shiny Server **deletes a worker's log on clean exit** — only crashed workers leave logs in `/var/log/shiny-server/`. To capture a traceback for a WS-disconnect, read `/var/log/shiny-server/*shyfem*` **while the worker is alive** (readable as the `shiny` group). The browser console shows only the SockJS close code (e.g. 4503), never the server traceback.

## Rollback

```bash
cd /home/razinka/shyfem/shyfem-ui
git log --oneline -5                                  # find the last-good commit
git checkout <last-good-commit> -- .                  # or revert the merge
# If a migration was applied and is the problem, restore the pre-migration backup:
cp shyfem_ui.db.bak.<timestamp> shyfem_ui.db          # OR: alembic downgrade -1
/opt/micromamba/envs/shiny/bin/pip install -e . --no-deps   # if version changed
touch restart.txt
# Re-verify /health.
```

## Deploy checklist (create one todo per item)

- [ ] Pre-flight: tree is the intended commit; app dir symlink confirmed; worker shiny version checked
- [ ] Diff scanned for shiny ≥1.6-only APIs without a `getattr` fallback
- [ ] (Schema) DB backed up, then `alembic upgrade head`, then `alembic current` confirms advance
- [ ] (Version) `pip install -e . --no-deps` to refresh metadata
- [ ] `touch restart.txt`
- [ ] `/health` returns 200 with the expected version
- [ ] Browser smoke test: login + no WS-disconnect
