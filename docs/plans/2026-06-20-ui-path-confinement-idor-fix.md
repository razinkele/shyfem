# Fix Plan — UI Path-Confinement IDOR (cross-user file read)

**Branch:** `fix/ui-path-confinement-idor`
**Source:** `docs/reviews/2026-06-20-full-codebase-deep-review.md` findings **H1** (`config.py:261-308`) and **H2** (`pages/postprocess.py:395-416` + visualize/grid_prep).
**Severity:** High — any authenticated user in prod (server mode, multi-user) can read/postprocess another user's model files.

## Root cause

`Config.validate_path()` (`config.py:261-308`) confines user-supplied paths to a set of **shared** roots:

```python
allowed_roots = [self.work_dir.resolve(), self.shyfem_dir.resolve(), Path("/tmp").resolve()]
```

These are global, not per-user. Because projects are also created under the shared `work_dir` (`home.py:554` → `validate_save_path`, confined to `work_dir`), one tenant's free-form path input (`data_path`, `shy_path`, `input_file`, …) resolves into another tenant's project files and is read / fed to `shyelab`. The handler's access check authorizes the user's *active* project (`editor_denied_reason`), but the path actually read is decoupled from that check.

The per-user sandbox primitive **already exists and is unused here**:
- `User.home_dir(user_data_root)` → `{user_data_root}/{username}/` with an escape guard (`models/user.py:51-67`).
- `Config.user_data_root` (`config.py:42`).
- `current_user()` reactive helper returns the **server-validated** user dict (`app.py:864`); every vulnerable handler already calls it next to the `validate_path` call (e.g. `postprocess.py:483`).
- Access gates (`access_control.py`) already fail-closed in server mode when `user is None`.

## Design

**Primary fix — structural per-user confinement.** Make path validation confine to the *requesting user's home* in server mode, reusing the existing identity. Cross-user reads then become impossible by construction.

Add to `Config`:

```python
def confine_path(self, path, user, *, must_exist=False, allow_write=False):
    """Resolve `path` and confine it to the requesting user's sandbox.

    server mode: allowed roots = [ user.home_dir(self.user_data_root),
                                   read-only shyfem_dir assets (testcases/examples, bin) ]
                 user is None  -> raise (fail-closed, mirrors identity_denied_reason)
                 /tmp and other users' homes are NOT allowed.
    local mode (single-user desktop, no auth): fall back to today's validate_path behavior.
    """
```

- Keep `validate_path`/`validate_save_path` as the local-mode / internal primitives; `confine_path` wraps them with the per-user allowlist.
- Drop `/tmp` from the general read allowlist (server mode). If any feature genuinely needs scratch space, give each user a sandboxed `…/home/<user>/tmp`.
- Read-only model assets (`testcases/examples`, `bin`) stay readable so tutorials/examples work.

**Project location.** Create new project dirs under the **owner's home** (`home.py`): default `project_dir` to `user.home_dir(config.user_data_root)/<slug>`, validate with `confine_path(..., allow_write=True)`. This makes confinement actually contain real project data.

**Secondary defense (H2) — bind the check to the path's owner.** After resolving a path, look up the `Project` whose `work_dir` contains it and enforce `editor_denied_reason` against *that* project, not the active one. Defense-in-depth; the primary confinement already blocks the cross-user case.

## Work breakdown (TDD — tests first)

1. **Red tests** (`tests/test_path_confinement.py`):
   - server mode: user A cannot `confine_path` into user B's home, `/etc/passwd`, `/tmp/x`, or another project's dir → `ValueError`.
   - server mode + `user is None` → raises (fail-closed).
   - user A *can* resolve a path inside their own home and read-only `testcases/examples`.
   - local mode: behavior unchanged (single-user).
2. **`Config.confine_path`** implemented to green (1).
3. **Migrate read/write handlers** to `confine_path(path, current_user(), …)` — they already resolve `current_user()` adjacently:
   - `postprocess.py` (×4: 404/498/614/770/1128), `visualize.py` (×2: 501/526), `grid_prep.py` (256/300), `run.py` (616/641/1262), `compare.py` (×4), `simulation.py` (286/363), `ibm.py` (416), `ensemble.py` (420/527/536), `partitioning.py` (214/253/262), `physics.py` (460), `mesh_builder.py` (1489), `file_service.py` (299/313), `components/timeseries.py` (367).
   - ~35 call sites across 14 modules; mechanical but must each thread the right user. `ui-security-reviewer` agent should review the diff.
4. **Project creation under home** (`home.py:528-575`, clone/import paths too).
5. **Secondary ownership binding** in postprocess/visualize read handlers.
6. **Regression:** full UI suite; the 7 picker path-traversal E2E tests (and add the missing sentinel from finding **H5** so they can't silently skip).

## Open decisions (need owner input before step 4+)

- **D1 — Existing project data.** Projects currently live under the shared `work_dir`. Options:
  - (a) **Data migration**: move each project dir into its owner's home and update `Project.work_dir` (Alembic data migration + filesystem move; needs the laguna deploy + DB backup via the new `deploy-ui` skill).
  - (b) **Grandfather**: leave existing dirs in place; allow a user to resolve a path inside a project they have access to (ownership binding), and only *new* projects land under home. Less disruptive, weaker structural guarantee.
- **D2 — Branch scope.** Ship (a) primary confinement + new-project relocation now and defer existing-data migration, or (b) the whole thing including migration, in one branch.

## Verification

- `CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest` (unit + new confinement tests).
- The picker traversal E2E (`tests/test_playwright_run_picker.py` family) with the new sentinel.
- Dispatch `ui-security-reviewer` on the final diff.
- Deploy via the `deploy-ui` skill (DB backup before any data migration).
