# SHYFEM-UI Round 3 Improvement Plan — Design (WIP)

**Created:** 2026-02-19
**Status:** IN PROGRESS — Sections 1/4 drafted, pending user review
**Baseline:** Phases 18–33 complete, 499 tests passing, 0 failed

---

## Scope Decisions

- **Themes:** All four — Test Hardening, UX Polish, Ops Readiness, Scientific Workflow
- **Structure:** Approach A — Test-First, Ship-Second (front-load testing gaps, then features)
- **Celery:** Planned for production → CeleryJobQueue mock tests are high priority
- **STR parameter search:** High priority UX item
- **Notifications:** Job completion/failure alerts need improvement
- **Phases:** ~10 total (34–43)

---

## Phase Overview (Draft)

```
Phase 34: STR validation engine tests        — Test hardening
Phase 35: Boundary editor + home helper tests — Test hardening
Phase 36: CeleryJobQueue mock tests           — Test hardening
Phase 37: STR parameter search                — Scientific workflow (high priority)
Phase 38: Job notification improvements       — UX polish
Phase 39: Rate limiter LRU + remove debug MW  — Ops readiness
Phase 40: Compare page diff colorization      — Scientific workflow
Phase 41: Batch shy→NetCDF conversion         — Scientific workflow
Phase 42: Workflow state persistence + misc   — UX polish (dark mode, ensemble stop-all)
Phase 43: Richer /health + request IDs        — Ops readiness
```

---

## Section 1: Test Hardening (Phases 34–36) — DRAFTED

### Phase 34: STR Validation Engine Tests

`validate_str_content()` in `str_editor.py:471-588` is a 120-line pure function with
structural checks, timing validation, depth sanity, range checking, and file existence
probing. Called on every save and validation click — zero dedicated tests.

**Tests (~15-20):**
- Parse errors → returns error list
- Missing `$end` → structural error with line number
- Extra `$end` → structural error
- Missing `$para` → error, missing `$title` → warning
- `itanf >= itend` → error
- `idt <= 0` → error
- `hzmin >= hzoff` → warning
- Unknown parameter → warning (but `itm*`/`idt*` prefixes allowed)
- Range violations from `COMMON_PARAMS` → warning
- `_check_range()` helper: `[min,max]`, `>0`, `>=0`
- `check_files=True` with missing/existing files
- `generate_section_template()` — each section returns valid content
- `get_parameter_help()` — known param returns help, unknown returns None

**File:** `tests/test_str_validation.py`

### Phase 35: Boundary Editor & Home Page Helper Tests

**Boundary editor** (`boundary_editor.py`, 351 lines): `generate_bound_section()` and
CSV import parsing are pure logic with zero unit tests.

**Tests (~10-12):**
- `generate_bound_section()` — single boundary, multiple, empty
- CSV import — valid, missing columns, wrong types
- Node validation — valid IDs, out-of-range, duplicates

**`_safe_filename()` in home.py (~5 tests):**
- Normal name → cleaned
- Unicode → stripped
- Empty/all-special → fallback
- Very long → truncated

### Phase 36: CeleryJobQueue Mock Tests

`CeleryJobQueue` (491 lines) is the production backend. Only health-check tests exist.

**Tests (~12-15):**
- `submit()` — creates Celery task, returns job ID, stores Redis metadata
- `cancel()` — revokes task, updates status
- `get_status()` — maps Celery states to `JobStatus` enum
- `list_jobs()` — retrieves from Redis, filters by session_id
- `get_output()` — reads stdout/stderr files
- `active_job_count` property
- Error paths: Redis failure, task not found, stale task

**Implementation:** `unittest.mock.patch` on `celery.Celery`, `redis.from_url`. No live Redis.

---

## Section 2: Scientific Workflow (Phases 37, 40–41) — TODO

### Phase 37: STR Parameter Search (high priority)
- Search/filter box in structured form view
- Filters across all sections by param name, description, or value
- Highlight matching params, collapse non-matching sections

### Phase 40: Compare Page Diff Colorization
- Red/green visual diff for STR param comparison
- File picker from active project outputs (replace manual path typing)

### Phase 41: Batch shy→NetCDF Conversion
- "Batch Convert" button on Post-Process page
- Runs `shyelab -convert` on selected `.shy` files
- Progress bar for multi-file conversion

---

## Section 3: UX Polish (Phases 38, 42) — TODO

### Phase 38: Job Notification Improvements
- More prominent job completion/failure alerts
- Persistent notification area or toast stack
- Optional browser Notification API integration

### Phase 42: Workflow State Persistence + Misc UX
- Workflow state survives tab navigation (persist to DB or session storage)
- Dark mode: restore saved preference on page load
- Ensemble: "Stop All" button at ensemble level

---

## Section 4: Ops Readiness (Phases 39, 43) — TODO

### Phase 39: Rate Limiter LRU + Debug Middleware Cleanup
- Add LRU eviction / time-based pruning to `_requests` dict
- Remove `_WsDebugMiddleware` (labeled "Temporary", shipped for 30+ phases)

### Phase 43: Richer /health + Request Correlation IDs
- `/health` returns: queue depth, worker count (Celery), DB response time ms
- Request ID middleware: generates UUID per request, propagates through logs
