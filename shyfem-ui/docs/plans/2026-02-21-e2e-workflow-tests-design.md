# E2E Workflow Tests Design

**Goal:** Add ~20 Playwright tests covering the 4 highest-value user workflows that currently have zero E2E coverage.

**Approach:** Single new test file (`test_playwright_workflows.py`) using the existing local-mode `pw_page` fixture. Tests run sequentially — Group 1 creates an active project that Groups 2-3 depend on.

## Test Groups

### Group 1: Project Creation & Activation (5 tests)

Tests the primary entry point: creating a project and making it active.

- `test_create_project` — Open New Project modal, fill name, submit, verify modal closes
- `test_project_appears_in_list` — Verify the created project appears in `#home-projects_list`
- `test_activate_project` — Click `#home-project_{id}` link, verify "Opened project" notification
- `test_active_project_propagates_to_files` — Switch to Files tab, verify "No project selected" is gone
- `test_active_project_propagates_to_simulation` — Switch to Simulation tab, verify sidebar renders

Key selectors: `#home-new_project_btn`, `#home-project_name`, `#home-create_project_btn`, `#home-projects_list`, `#home-project_{id}`

### Group 2: Simulation STR Editor (5 tests)

Tests the STR editor core actions (template, quick settings, sub-tabs).

- `test_select_template_shows_preview` — Choose "basic_2d" from `#simulation-template_select`, verify `#simulation-template_preview` populates
- `test_apply_template` — Click "Apply Template", verify editor content appears
- `test_quick_settings_apply` — Fill quick start/end/dt/output fields, click `#simulation-apply_quick_btn`
- `test_simulation_subtabs` — Switch between Editor, Sections, Boundaries, Parameter Reference sub-tabs
- `test_save_as_modal` — Click `#simulation-save_as_btn`, verify modal with `#simulation-save_path` appears

Key selectors: `#simulation-template_select`, `#simulation-apply_template_btn`, `#simulation-quick_start`, `#simulation-quick_end`, `#simulation-quick_dt`, `#simulation-quick_output`, `#simulation-apply_quick_btn`, `#simulation-save_as_btn`, `#simulation-save_path`

### Group 3: Files Page with Active Project (5 tests)

Tests the file management UI when a project is active.

- `test_files_shows_content_with_project` — Verify storage bar and filter buttons render (not "No project selected")
- `test_file_filter_buttons_present` — Verify all 7 filter buttons exist (`#files-filter_all` through `#files-filter_other`)
- `test_file_filter_click_changes_style` — Click a filter button, verify it gets `btn-primary` class
- `test_file_table_present` — Verify the file table element exists inside `#files-files_content`
- `test_upload_area_present` — Verify `#files-file_upload-file_input` exists

Key selectors: `#files-files_content`, `#files-filter_all` through `#files-filter_other`, `#files-file_upload-file_input`

### Group 4: Tutorial Navigation (5 tests)

Tests the tutorial page interactivity.

- `test_default_step_content_renders` — Verify `#tutorial-step_content` has content on page load
- `test_click_simulation_link` — Click `#tutorial-select_mm_hyd_01`, verify step_content text changes
- `test_mark_complete_advances_progress` — Click `#tutorial-mark_complete`, verify progress bar width increases
- `test_phase_accordion_present` — Verify `#tutorial-phase_accordion` exists and has expandable panels
- `test_nav_link_exists_in_step` — Verify a "Go to" navigation link exists in step content

Key selectors: `#tutorial-step_content`, `#tutorial-select_{name}`, `#tutorial-mark_complete`, `#tutorial-progress_bar`, `#tutorial-phase_accordion`

## Constraints

- All tests use the local-mode `pw_page` (session-scoped, shared page)
- Group 1 must run before Groups 2-3 (they depend on an active project)
- Group 4 is independent (tutorial renders without an active project)
- No file I/O or real SHYFEM binary needed
- Tests check UI state, not database state
