# E2E Test Expansion Design

**Date:** 2026-02-21
**Goal:** Add Playwright E2E tests for newer features — Files tab, Admin panel, Tutorial tab, login/logout, sharing UI, and role-based access control.

## Current State

- 88 Playwright tests across 5 files covering original 9 tabs
- All run in **local mode** (auth bypassed)
- Missing tabs in `_test_app.py`: Tutorial, Files, Admin
- Zero E2E coverage for: auth flows, admin user management, sharing UI, file management, tutorial

## Architecture: Two-Server Approach

### Server 1: Local Mode (existing)

Extend the existing `_test_app.py` and `pw_page` fixture to include the 3 missing tabs (Tutorial, Files, Admin). Tests verify page rendering and basic interactions without auth.

### Server 2: Server Mode (new)

A second subprocess started with `DEPLOYMENT_MODE=server` and `DEFAULT_ADMIN_PASSWORD=testpass`. A new `pw_auth_page` session-scoped fixture logs in as admin before yielding. Tests verify auth flows, role-based visibility, and sharing UI.

## Infrastructure Changes

### `_test_app.py`

Add missing imports and tabs:
- `from shyfem_ui.pages import tutorial, files, admin`
- Add `nav_panel("Tutorial", ...)`, `nav_panel("Files", ...)`, `nav_panel("Admin", ...)`
- Wire server calls: `tutorial.tutorial_server(...)`, `files.files_server(...)`, `admin.admin_server(...)`
- Pass `auth_service` to `home_server` (needed for sharing UI)

### `conftest.py`

New fixtures for server-mode testing:
- `auth_app_port` — free port for the server-mode instance
- `_auth_app_server` — subprocess with `DEPLOYMENT_MODE=server`, `DEFAULT_ADMIN_PASSWORD=testpass`, `DEFAULT_ADMIN_USERNAME=admin`
- `auth_live_server` — base URL for the auth server
- `pw_auth_page` — browser page that logs in as admin at fixture creation
- `_login(page, url, username, password)` — helper to fill login form and submit

For server-mode, use the real `create_app()` via a thin entry point (`_test_auth_app.py`) rather than the stub, since auth middleware must be active.

## Test Plan

### File 1: `test_playwright_new_tabs.py` (~12 tests, local mode)

| Test | Verifies |
|------|----------|
| `test_nav_tutorial_tab` | Tutorial tab navigation |
| `test_nav_files_tab` | Files tab navigation |
| `test_nav_admin_tab` | Admin tab navigation |
| `test_tutorial_tab_renders` | Phase cards visible |
| `test_tutorial_create_project_button` | Button exists |
| `test_tutorial_phase_content` | Phase sections have content |
| `test_files_tab_renders` | Upload section visible |
| `test_files_storage_summary` | Storage bar renders |
| `test_files_type_filter_buttons` | All 7 filter buttons present |
| `test_files_empty_state` | "No files" or empty table when no project |
| `test_admin_tab_renders` | User table area visible |
| `test_admin_create_user_form` | Form fields present |

### File 2: `test_playwright_auth.py` (~12 tests, server mode)

| Test | Verifies |
|------|----------|
| `test_login_page_renders` | Login form with username/password fields |
| `test_login_success` | Valid credentials → Dashboard |
| `test_login_failure` | Bad credentials → error alert |
| `test_logout_redirects` | Logout → login page |
| `test_admin_user_table_shows_users` | Admin tab lists seeded admin user |
| `test_admin_create_user` | Form submit → new user in table |
| `test_admin_toggle_active` | Deactivate/reactivate user |
| `test_admin_reset_password` | Reset password works |
| `test_share_button_visible_for_owner` | Share button on owned project |
| `test_share_modal_opens` | Modal with permissions table + add form |
| `test_share_add_permission` | Add user → appears in permissions |
| `test_share_remove_permission` | Remove → disappears from permissions |

## Constraints

- **Session-scoped pages**: One page per server instance, tests must clean up (dismiss modals, return to Dashboard)
- **Server-mode login**: `pw_auth_page` logs in once; logout test must re-login afterward
- **`_test_auth_app.py`**: Uses real `create_app()` with server-mode config for full middleware stack
- **Markers**: All new tests get `@pytest.mark.e2e`
- **Exclusion**: All `test_playwright_*` files already excluded from default pytest via `--ignore-glob`

## Estimated: ~24 new tests, 2 new test files, 2 infrastructure files modified/created
