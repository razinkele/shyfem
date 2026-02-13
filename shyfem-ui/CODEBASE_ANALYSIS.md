# Codebase Analysis & Inconsistencies Report

**Date:** February 13, 2026
**Target Environment:** Micromamba / Shiny
**Repository:** `shyfem-ui`

## Executive Summary

The `shyfem-ui` codebase exhibits a solid architectural foundation with a clear separation between UI logic (Shiny pages) and business logic (Services/Parsers). However, there are significant inconsistencies in dependency management and testing strategies that conflict with the intended Micromamba-based deployment workflow. Consolidating these areas will improve maintainability, build determinism, and CI reliability.

---

## 1. Dependency Management & Environment

### Observations
1.  **Missing Environment Definition**: The project relies on `requirements.txt` and `pyproject.toml` (standard for `pip`), but lacks an `environment.yml` file. This contradicts the requirement to run in a **Micromamba** environment.
2.  **Dual Sources of Truth**: `requirements.txt` duplicates dependencies found in `pyproject.toml`, leading to potential version drift.
3.  **Binary Dependencies**: libraries like `netCDF4`, `xarray`, and `scipy` depend on complex C/Fortran binaries. Installing these via `pip` instead of `conda-forge` often leads to slower builds and compatibility issues in scientific stacks.

### Recommendations
*   **Create `environment.yml`**: Establish this as the single source of truth for the runtime environment. It should utilize `conda-forge` for binary-heavy scientific packages.
*   **Remove `requirements.txt`**: Delete this file to prevent confusion.
*   **Update `pyproject.toml`**: Use this solely for package metadata and "abstract" dependencies (install_requires), letting conda handle the "concrete" pinned versions.

---

## 2. Testing Strategy

### Observations
1.  **Framework Redundancy**: The `tests/` directory contains E2E tests for **both** Selenium (`test_selenium_*.py`) and Playwright (`test_playwright_*.py`).
2.  **Maintenance Overhead**: `tests/conftest.py` is bloated, maintaining complex fixtures for two distinct browser automation drivers.
3.  **Micromamba Compatibility**: Selenium is brittle in isolated conda/container environments (requires external drivers). Playwright is more self-contained and reliable for modern Shiny applications.

### Recommendations
*   **Consolidate on Playwright**: It is the modern standard for Shiny app testing.
*   **Delete Selenium Tests**: Remove `test_selenium_auth.py`, `test_selenium_forms.py`, `test_selenium_navigation.py` and specific selenium fixtures from `conftest.py`.

---

## 3. Code Style & Robustness

### Observations
1.  **Defensive Imports**: `shyfem_ui/app.py` uses `try...except ImportError` for `shinyswatch`.
    *   *Analysis*: In a managed Micromamba environment, the environment is deterministic. Dependencies are either present (per `environment.yml`) or the deployment is broken.
    *   *Impact*: Defensive coding here masks deployment issues and clutters the code.
2.  **Logging**: Consistency varies between `logging` (used in services like `job_local.py`) and `print` statements (often found in UI components).

### Recommendations
*   **Enforce Hard Imports**: Add `shinyswatch` to `environment.yml` and remove the try/except block in `app.py`. Fail fast if the environment is corrupt.
*   **Standardize Logging**: adopt the Python `logging` module across all `services/` and `components/`.

---

## 4. Architecture & Parsing

### Observations
1.  **Manual Parsing**: `shyfem_ui/services/parser_grd.py` relies on manual string splitting and list indexing.
    *   *Risk*: Malformed `.grd` files may cause generic `IndexError` crashes instead of helpful validation messages.
2.  **File Structure**: The project structure is otherwise healthy, with a clear `app.py` entry point and modular `pages/` directory.

### Recommendations
*   **Robust Error Handling**: Wrap parsing logic in `try...except` blocks that raise domain-specific errors (e.g., `GridParseError`) to provide user feedback in the UI.

---

## Action Plan

1.  **Environment**: Generate `environment.yml` for `conda-forge` and delete `requirements.txt`.
2.  **Tests**: Delete all `test_selenium_*.py` files and remove Selenium headers from `tests/conftest.py`.
3.  **Refactor**: Simplify `shyfem_ui/app.py` imports.
