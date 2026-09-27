# Box-model hourly cache — UI — Implementation Plan

**Goal:** let a user ask for the hourly cache and actually see hourly detail. The
last deferred item of the Box model feature (spec §8), and the only one whose
back end is already finished.

**What already exists.** `boxmodel_cache_cli --hourly` streams
`state_hourly.parquet` (`stamp`, `box`, and every `STATE_VARS` column as
float32, one calendar day flushed at a time so peak memory is bounded),
`start_build(..., hourly=True)` appends the flag, `meta.json` records
`"hourly"`, and `load_cache` reads the frame into `CachedRun.state_hourly` when
the file is there. **Nothing in the UI ever passes `hourly=True`**, so the
column has never been written in production and the loader has never had a
frame to load.

**What the spec asks for**

- §138: `state_hourly.parquet` is optional, "default **off** for runs longer
  than 5 years".
- §246: on the Map, the quantity is "the value on the day chosen by a slider
  (**hourly when the hourly cache exists and the window is ≤ 31 days**)".
- §355: "Hourly cache off by default for runs longer than 5 years; can be
  requested."
- §147: for the 22-year Curonian run the hourly cache is 50–100 MB against a
  10–20 MB daily one, and it counts against `SHYFEM_UI_MAX_PROJECT_STORAGE_MB`.

## A live defect found while scoping this, which the slice must fix first

The three published Curonian caches **already contain** `state_hourly.parquet`
(183, 184 and 207 MB), built outside the UI. `load_cache` reads it
unconditionally whenever the file exists, and the Box model page's
`cached_result()` calls exactly that loader. So today, opening the page on that
project pulls **6,100,440 rows, about 250 MB before pandas overhead**, into the
worker that serves every session, at the head of the expensive chain, for data
no part of the UI has ever displayed.

Measured, not estimated: `pq.ParquetFile(...).metadata` reports 6,100,440 rows
over 9 columns in 8,766 row groups, and the row groups are one per calendar day
because the builder flushes a day at a time.

So the loader changes before anything else: `load_cache` stops materialising the
hourly frame, exactly as `load_cache_state` already refuses to, and a new
`read_hourly_window(cache_dir, lo, hi)` reads only the visible window with
pyarrow `stamp` filters, which prune whole days.

## A correction on "hourly"

The name is only a name: the frame holds raw records at the model's output step.
For these runs `meta["step_seconds"]` is 3600, so they genuinely are hourly, but
a different run need not be. The slider's step therefore comes from
`step_seconds`, never from a hardcoded hour, and the label says "model output
step" rather than promising hours.

## Scope

1. **Request it.** A checkbox beside Build cache, off by default, wired through
   to `start_build(hourly=...)`. Its help text names the cost, because the user
   pays for it out of the project's storage quota.
2. **Report it.** Whether the *published* cache has hourly data, read from
   `meta["hourly"]`, so nobody has to rebuild to find out.
3. **Use it on the Map.** With hourly data present and a window of at most
   `HOURLY_WINDOW_DAYS` (31), the day slider steps by the hour and the map
   selects on the timestamp. Otherwise it stays exactly as it is today.
4. **Use it on the Time series.** Same rule: hourly points for the selected box
   instead of daily means inside a short enough window.

## Out of scope

Compare stays daily (it intersects *days* across runs, and a second run may not
have an hourly cache at all); skill metrics stay daily, because the
observations and the Curonian reference scripts are daily; the Setup tab is
untouched.

## Rules this has to respect

- **Fail soft, never fail closed.** No hourly frame, or a window wider than the
  cap, means the daily behaviour, not an error. A cache built before this
  change is not stale and must not be reported as such.
- **Say why.** When hourly exists but the window is too wide, the page says so
  once, rather than silently showing daily data under an hourly-looking
  control.
- **One rule, one place.** The "can we use hourly right now" decision is a
  single helper used by the map and the series, so the two can never disagree.
- Reads come off disk, so every new frame access is inside a `try` and becomes
  a page message ([[the Compare-chain rule from #92]]).
- Worktree `/tmp/claude-1000/wt-hourly`, branch `feat/boxmodel-hourly-ui`.
  Never a branch checkout in `~/shyfem`: laguna serves that tree live.

## Tests

- Service: `start_build` passes `--hourly` only when asked (already covered;
  extend if not), and `meta["hourly"]` survives publish.
- Page, behavioural where possible: the helper's decision table (no frame /
  narrow window / wide window / empty frame), the slider's step and bounds in
  both modes, the map's value selection at an hour, and the series frame.
- E2E: build the fixture run with the box ticked, then assert the slider is
  hourly and the series has more points than days.
- Every new test must fail before its change: mutation-check the window rule
  and the checkbox wiring, which are the two places a silent regression would
  hide.
