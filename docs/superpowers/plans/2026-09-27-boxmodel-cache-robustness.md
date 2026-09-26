# Box-model cache robustness batch — Implementation Plan

**Goal:** Clear the five deferred box-model follow-ups that have a real failure mode or waste real work. Recorded in the PR #78 body and carried through PRs #85–#88.

**Why these five together:** they are all about the cache path — the child process, its reaper, the quota that counts it, and the two page calcs that read it. Each is small; none is a feature.

| # | Item | Failure today |
|---|---|---|
| 1 | Daemon heartbeat thread in the build child | The child beats `progress.json` every 500 records. A single large Parquet write, or the final `run.log` tail, can exceed the 90 s `LIVE_TMP_SECONDS` window — so **another worker's page-load reaper deletes a healthy, running build's tmp dir**. |
| 2 | `read_stats` per-row width check | A stats file truncated mid-line reports pandas' column-count error with no file name. |
| 3 | Parse the grid once | `polygons_result` holds a parsed `GrdFile` (it uses it for the EPSG decision) and then hands `dissolve_boxes_from_grid` a **path**, which re-parses the whole `.grd`. |
| 4 | Quota double-count | `_cache_bytes` walks `.tmp-*` and `.old-*` alongside the published run, so during the two-step publish a run is counted **twice** against `SHYFEM_UI_MAX_PROJECT_STORAGE_MB`. |
| 5 | Unguarded date read | `_compare_bounds`/`cmp_days` read `state_daily["date"]` outside a `try`, so a foreign or hand-edited cache raises inside a calc instead of becoming a page message. |

## Global Constraints

- Item 1 must not make a **hung** child immortal. Today the 90 s window doubles as liveness *and* hang detection; a reliable heartbeat removes the second job, so the reaper gains an absolute age cap (the configured build timeout plus a margin, default 30 min) beyond which a tmp dir is dead regardless of heartbeats.
- A **crashed** child stops beating by construction (daemon thread dies with the process), which is what keeps the reaper working.
- The heartbeat must not race the main thread's writes: `atomic_json` is atomic per write, and the thread re-publishes the last payload under a lock rather than inventing one.
- The CLI still imports nothing from `shyfem_ui.services` (an AST test pins it).
- Item 4 counts **committed** bytes only: a build in flight stops counting until it publishes. That is the intended trade-off, stated in the docstring — the alternative is double-counting every publish.
- Worktree `/tmp/claude-1000/wt-rb`, branch `fix/boxmodel-cache-robustness`; worker interpreter for every run; E2E never concurrently with the unit suite; never `git stash`/`checkout --`/`reset` in a shared worktree.
- Commit style: conventional commits, trailer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## Split

- **Item 1 (coordinator):** `shyfem_ui/boxmodel_cache_cli.py`, `shyfem_ui/services/boxmodel_cache.py`, `tests/test_boxmodel_cache_cli.py`, `tests/test_boxmodel_cache_service.py`.
- **Items 2–5 (one agent):** `shyfem_ui/boxmodel_output.py`, `shyfem_ui/services/boxmodel_polygons.py`, `shyfem_ui/services/file_service.py`, `shyfem_ui/pages/boxmodel.py` and their tests.

No file is touched by both.

## Item 1 — the heartbeat, in detail

- `_Progress` gains a `threading.Lock`, remembers its last payload, and grows `touch()` (re-publish the last payload with a fresh `updated`) plus `start_heartbeat()`/`stop()`.
- The thread is a daemon, interval `HEARTBEAT_SECONDS = 20` (well inside 90), started once the out dir exists and stopped in a `finally` before the process leaves.
- `progress.json` gains `"pid"`: the reaper can then distinguish "no longer beating because it died" from "beating".
- Reaper: `_tmp_dir_is_dead_or_error` keeps the mtime rule and adds the absolute cap. The cap comes from the same config the parent uses to bound a build, so an operator who raises the timeout raises the cap with it.
- Tests: the thread refreshes `progress.json` while the main thread sleeps past the window; the payload keeps its record count (a touch is not a reset); the thread stops on normal exit and on error; a tmp dir older than the cap is dead even with a fresh heartbeat; the existing cadence test still holds.
