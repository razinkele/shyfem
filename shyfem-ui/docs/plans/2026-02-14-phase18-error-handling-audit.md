# Phase 18: Error Handling Audit — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace all 28 silent exception handlers across 8 files with logged handlers.

**Architecture:** Add `logger = logging.getLogger(__name__)` to 6 files that lack it. Replace every `except ...: pass/continue/return` with a `logger.debug()`/`logger.warning()` call. Medium+ severity handlers also get `ui.notification_show()`.

**Tech Stack:** Python stdlib `logging`, Shiny `ui.notification_show`

---

### Task 1: Add logging to `components/str_editor.py` (3 handlers)

**Files:**
- Modify: `shyfem_ui/components/str_editor.py:1-3` (add import)
- Modify: `shyfem_ui/components/str_editor.py:146-147` (medium — form sync)
- Modify: `shyfem_ui/components/str_editor.py:171-172` (low — field conversion)
- Modify: `shyfem_ui/components/str_editor.py:602-603` (low — range parsing)

**Step 1: Add logger import**

After existing imports (line 7), add:

```python
import logging

logger = logging.getLogger(__name__)
```

**Step 2: Fix handler at line 146 (medium — form re-parse)**

Replace:
```python
            except Exception:
                pass
```

With:
```python
            except Exception:
                logger.warning("Failed to re-parse editor content for form sync", exc_info=True)
```

**Step 3: Fix handler at line 171 (low — form field conversion)**

Replace:
```python
                    except Exception:
                        continue
```

With:
```python
                    except Exception:
                        logger.debug("Skipping form field %s conversion", field_id, exc_info=True)
                        continue
```

**Step 4: Fix handler at line 602 (low — range value parsing)**

Replace:
```python
        except ValueError:
            pass
```

With:
```python
        except ValueError:
            logger.debug("Could not parse range '%s' for %s.%s", options_str, section, param)
```

**Step 5: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_parser_str.py tests/test_components.py -v --tb=short`
Expected: All existing tests PASS

**Step 6: Commit**

```bash
git add shyfem_ui/components/str_editor.py
git commit -m "fix: add logging to silent exception handlers in str_editor.py"
```

---

### Task 2: Add logging to `components/timeseries.py` (5 handlers)

**Files:**
- Modify: `shyfem_ui/components/timeseries.py:1-14` (add import)
- Modify: `shyfem_ui/components/timeseries.py:170-171` (low — column selection)
- Modify: `shyfem_ui/components/timeseries.py:276-277` (low — column selection)
- Modify: `shyfem_ui/components/timeseries.py:385-386` (low — column selection)
- Modify: `shyfem_ui/components/timeseries.py:433` (low — CSV fallback)
- Modify: `shyfem_ui/components/timeseries.py:447-448` (low — numeric parsing)

**Step 1: Add logger import**

After line 14 (`from pathlib import Path`), add:

```python
import logging

logger = logging.getLogger(__name__)
```

**Step 2: Fix 3 identical column selection handlers (lines 170, 276, 385)**

Each one replaces:
```python
        except Exception:
            selected = columns[1:] if len(columns) > 1 else []
```

With:
```python
        except Exception:
            logger.debug("Column selection input unavailable, using defaults")
            selected = columns[1:] if len(columns) > 1 else []
```

Do this at all three locations.

**Step 3: Fix CSV fallback handler (line 433)**

Replace:
```python
    except Exception:
        # Fall back to whitespace-delimited
```

With:
```python
    except Exception:
        logger.debug("CSV parsing failed for %s, falling back to whitespace-delimited", path)
        # Fall back to whitespace-delimited
```

**Step 4: Fix numeric line skip handler (line 447)**

Replace:
```python
                    except ValueError:
                        continue
```

With:
```python
                    except ValueError:
                        logger.debug("Skipping non-numeric line %d in %s", i, path)
                        continue
```

**Step 5: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_timeseries_stats.py tests/test_components.py -v --tb=short`
Expected: All existing tests PASS

**Step 6: Commit**

```bash
git add shyfem_ui/components/timeseries.py
git commit -m "fix: add logging to silent exception handlers in timeseries.py"
```

---

### Task 3: Add logging to `pages/ensemble.py` (7 handlers)

**Files:**
- Modify: `shyfem_ui/pages/ensemble.py:1-14` (add import)
- Modify: `shyfem_ui/pages/ensemble.py:300-301` (low — form field)
- Modify: `shyfem_ui/pages/ensemble.py:304-305` (low — form field)
- Modify: `shyfem_ui/pages/ensemble.py:308-309` (low — form field)
- Modify: `shyfem_ui/pages/ensemble.py:565-567` (low — poll retry)
- Modify: `shyfem_ui/pages/ensemble.py:789-794` (low — type coercion)
- Modify: `shyfem_ui/pages/ensemble.py:836-837` (medium — file read)
- Modify: `shyfem_ui/pages/ensemble.py:929-930` (medium — envelope computation)

**Step 1: Add logger import**

After line 14 (`from typing import Any`), add:

```python
import logging

logger = logging.getLogger(__name__)
```

**Step 2: Fix 3 form field handlers (lines 300, 304, 308)**

Replace each pattern like:
```python
            except Exception:
                section = var["section"]
```

With:
```python
            except Exception:
                logger.debug("Form field var_section_%d unavailable, using cached value", i)
                section = var["section"]
```

Similarly for `var_param_{i}` and `var_values_{i}`.

**Step 3: Fix poll retry handler (line 565)**

Replace:
```python
        except Exception:
            # Silently retry on next cycle
            reactive.invalidate_later(5)
```

With:
```python
        except Exception:
            logger.debug("Ensemble status poll failed, retrying in 5s", exc_info=True)
            reactive.invalidate_later(5)
```

**Step 4: Fix type coercion handlers (lines 789, 793)**

Replace:
```python
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value
```

With:
```python
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        logger.debug("Value '%s' is not numeric, keeping as string", value)
    return value
```

Note: Only the second `except ValueError` gets the log — the first is expected to fail for floats.

**Step 5: Fix file read handler (line 836) — medium severity**

Replace:
```python
    except Exception:
        return []
```

With:
```python
    except Exception:
        logger.warning("Failed to load time series from %s", path, exc_info=True)
        return []
```

**Step 6: Fix envelope computation handler (line 929) — medium severity**

Replace:
```python
        except Exception:
            pass
```

With:
```python
        except Exception:
            logger.warning("Ensemble envelope computation failed", exc_info=True)
```

Note: No `ui.notification_show` here because this is inside a `@render_widget` function (the `_build_envelope_chart` is a standalone function, not a reactive handler with access to `ui`). The logger.warning is sufficient.

**Step 7: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_ensemble_remove.py -v --tb=short`
Expected: All existing tests PASS

**Step 8: Commit**

```bash
git add shyfem_ui/pages/ensemble.py
git commit -m "fix: add logging to silent exception handlers in ensemble.py"
```

---

### Task 4: Add logging to `pages/postprocess.py` (4 handlers)

**Files:**
- Modify: `shyfem_ui/pages/postprocess.py:1-14` (add import)
- Modify: `shyfem_ui/pages/postprocess.py:378-379` (low — var selection)
- Modify: `shyfem_ui/pages/postprocess.py:386-387` (low — layer selection)
- Modify: `shyfem_ui/pages/postprocess.py:624-625` (low — file stat)
- Modify: `shyfem_ui/pages/postprocess.py:764-765` (low — numeric line)
- Modify: `shyfem_ui/pages/postprocess.py:776-777` (medium — preview)

**Step 1: Add logger import**

After line 12 (`import re`), add:

```python
import logging

logger = logging.getLogger(__name__)
```

**Step 2: Fix var selection handler (line 378)**

Replace:
```python
        except Exception:
            pass
```

With:
```python
        except Exception:
            logger.debug("Variable selection input unavailable")
```

**Step 3: Fix layer selection handler (line 386)**

Replace:
```python
        except Exception:
            pass
```

With:
```python
        except Exception:
            logger.debug("Layer selection input unavailable")
```

**Step 4: Fix file stat handler (line 624)**

Replace:
```python
            except Exception:
                size = 0
```

With:
```python
            except Exception:
                logger.debug("Could not stat file %s", f)
                size = 0
```

**Step 5: Fix numeric line handler (line 764)**

Replace:
```python
                    except ValueError:
                        continue
```

With:
```python
                    except ValueError:
                        logger.debug("Skipping non-numeric line in time series file")
                        continue
```

**Step 6: Fix preview handler (line 776) — medium severity**

Replace:
```python
        except Exception:
            pass
```

With:
```python
        except Exception:
            logger.warning("Failed to load time series preview", exc_info=True)
```

**Step 7: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_postprocess_helpers.py -v --tb=short`
Expected: All existing tests PASS

**Step 8: Commit**

```bash
git add shyfem_ui/pages/postprocess.py
git commit -m "fix: add logging to silent exception handlers in postprocess.py"
```

---

### Task 5: Add logging to `pages/run.py` (2 handlers)

**Files:**
- Modify: `shyfem_ui/pages/run.py:301-303` (low — poll retry)
- Modify: `shyfem_ui/pages/run.py:813-814` (low — template selection)

Note: `run.py` already has `import logging` and `logger = logging.getLogger(__name__)`.

**Step 1: Fix poll retry handler (line 301)**

Replace:
```python
        except Exception:
            # Silently retry on next cycle — avoid killing the poll loop
            reactive.invalidate_later(5)
```

With:
```python
        except Exception:
            logger.debug("Auto-refresh poll failed, retrying in 5s", exc_info=True)
            reactive.invalidate_later(5)
```

**Step 2: Fix template selection handler (line 813)**

Replace:
```python
        except Exception:
            return None
```

With:
```python
        except Exception:
            logger.debug("Workflow template selection unavailable")
            return None
```

**Step 3: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run_helpers.py -v --tb=short`
Expected: All existing tests PASS

**Step 4: Commit**

```bash
git add shyfem_ui/pages/run.py
git commit -m "fix: add logging to silent exception handlers in run.py"
```

---

### Task 6: Add logging to `pages/compare.py` (2 handlers)

**Files:**
- Modify: `shyfem_ui/pages/compare.py:1-14` (add import)
- Modify: `shyfem_ui/pages/compare.py:165-166` (low — job ID input)
- Modify: `shyfem_ui/pages/compare.py:466-467` (low — numeric line)

**Step 1: Add logger import**

After line 10 (`from pathlib import Path`), add:

```python
import logging

logger = logging.getLogger(__name__)
```

**Step 2: Fix job ID input handler (line 165)**

Replace:
```python
        except Exception:
            return
```

With:
```python
        except Exception:
            logger.debug("Job ID inputs unavailable, skipping comparison")
            return
```

**Step 3: Fix numeric line handler (line 466)**

Replace:
```python
            except ValueError:
                continue
```

With:
```python
            except ValueError:
                logger.debug("Skipping non-numeric line in time series")
                continue
```

**Step 4: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_pages_helpers.py -v --tb=short`
Expected: All existing tests PASS

**Step 5: Commit**

```bash
git add shyfem_ui/pages/compare.py
git commit -m "fix: add logging to silent exception handlers in compare.py"
```

---

### Task 7: Add logging to `db/base.py` (1 handler)

**Files:**
- Modify: `shyfem_ui/db/base.py:112-114`

Note: `base.py` already has `import logging` and `logger`.

**Step 1: Fix session rollback handler (line 112)**

Replace:
```python
    except Exception:
        session.rollback()
        raise
```

With:
```python
    except Exception:
        logger.exception("Database session error, rolling back")
        session.rollback()
        raise
```

**Step 2: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_config.py -v --tb=short`
Expected: All existing tests PASS

**Step 3: Commit**

```bash
git add shyfem_ui/db/base.py
git commit -m "fix: add logging to silent exception handler in db/base.py"
```

---

### Task 8: Add logging to `services/job_celery.py` (4 handlers)

**Files:**
- Modify: `shyfem_ui/services/job_celery.py:1-14` (add import)
- Modify: `shyfem_ui/services/job_celery.py:367-368` (medium — file read)
- Modify: `shyfem_ui/services/job_celery.py:400-401` (low — file cleanup)
- Modify: `shyfem_ui/services/job_celery.py:431-432` (medium — health check)
- Modify: `shyfem_ui/services/job_celery.py:455-456` (low — worker inspect)

**Step 1: Add logger import**

After line 13 (`import json`), add:

```python
import logging

logger = logging.getLogger(__name__)
```

**Step 2: Fix file read handler (line 367) — medium severity**

Replace:
```python
        except Exception:
            return ""
```

With:
```python
        except Exception:
            logger.warning("Failed to read output file %s", path, exc_info=True)
            return ""
```

**Step 3: Fix file cleanup handler (line 400) — low severity**

Replace:
```python
                        except Exception:
                            pass
```

With:
```python
                        except Exception:
                            logger.debug("Failed to clean up file %s", fp)
```

**Step 4: Fix health check handler (line 431) — medium severity**

Replace:
```python
        except Exception:
            return result
```

With:
```python
        except Exception:
            logger.warning("Redis health check failed", exc_info=True)
            return result
```

**Step 5: Fix worker inspect handler (line 455) — low severity**

Replace:
```python
        except Exception:
            pass
```

With:
```python
        except Exception:
            logger.debug("Failed to inspect Celery workers", exc_info=True)
```

**Step 6: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_celery_health.py -v --tb=short`
Expected: All existing tests PASS

**Step 7: Commit**

```bash
git add shyfem_ui/services/job_celery.py
git commit -m "fix: add logging to silent exception handlers in job_celery.py"
```

---

### Task 9: Update TODO_NEXT.md and final verification

**Files:**
- Modify: `TODO_NEXT.md` — check off Phase 18 items

**Step 1: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v --tb=short --ignore=tests/test_playwright_active_project.py --ignore=tests/test_playwright_dashboard.py --ignore=tests/test_playwright_interactions.py --ignore=tests/test_playwright_navigation.py --ignore=tests/test_playwright_pages.py`
Expected: 0 new failures (17 pre-existing async failures are expected)

**Step 2: Verify no remaining bare `pass` handlers**

Run: `cd /home/razinka/shyfem/shyfem-ui && grep -n "except.*:" shyfem_ui/components/str_editor.py shyfem_ui/components/timeseries.py shyfem_ui/pages/ensemble.py shyfem_ui/pages/postprocess.py shyfem_ui/pages/run.py shyfem_ui/pages/compare.py shyfem_ui/db/base.py shyfem_ui/services/job_celery.py | grep -E ":\s*(pass|continue)\s*$"`
Expected: 0 matches (all handlers now have logging before pass/continue)

**Step 3: Update TODO_NEXT.md**

Check off all 18.x items.

**Step 4: Commit**

```bash
git add TODO_NEXT.md
git commit -m "docs: mark phase 18 error handling audit complete"
```
