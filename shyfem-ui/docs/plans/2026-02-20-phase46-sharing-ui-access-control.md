# Phase 46: Sharing UI + Access Control Implementation Plan

> **Status:** COMPLETE (2026-02-21) — 27 new tests, 976 total passing, 5 commits merged to main.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add access control enforcement at all permission-sensitive endpoints and a Share modal UI so project owners can grant/revoke access to other users.

**Architecture:** A single `check_project_access()` helper in `services/access_control.py` is called inline at each enforcement point (project_context load, job submit, file upload/delete, admin page). Share UI lives in `pages/home.py` as a modal triggered by a "Share" button on project cards, using the existing `SharingService`.

**Tech Stack:** Shiny for Python, SQLAlchemy 2.0, pytest, existing AuthService/SharingService/SessionAuthMiddleware from Phase 45.

---

### Task 1: Access control helper + tests

**Files:**
- Create: `shyfem_ui/services/access_control.py`
- Create: `tests/test_access_control.py`

**Step 1: Write the failing tests**

Create `tests/test_access_control.py`:

```python
"""Tests for access control helper."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models.project import Project
from shyfem_ui.models.user import ProjectPermission, User


@pytest.fixture
def db_factory():
    from shyfem_ui.models import project as _p, user as _u  # noqa: F841
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def setup(db_factory):
    """Create alice (owner), bob (no access), charlie (viewer), admin user, and a project."""
    db = db_factory()
    alice = User(username="alice", password_hash="x", role="user")
    bob = User(username="bob", password_hash="x", role="user")
    charlie = User(username="charlie", password_hash="x", role="user")
    admin = User(username="admin", password_hash="x", role="admin")
    db.add_all([alice, bob, charlie, admin])
    db.flush()

    proj = Project(name="P1", work_dir="/tmp/p1", owner_id=alice.id)
    db.add(proj)
    db.flush()

    perm = ProjectPermission(project_id=proj.id, user_id=charlie.id, role="viewer")
    db.add(perm)
    db.commit()

    data = {
        "alice_id": alice.id,
        "bob_id": bob.id,
        "charlie_id": charlie.id,
        "admin_id": admin.id,
        "project_id": proj.id,
    }
    db.close()
    return data


def _user(uid, role="user"):
    """Helper to build a user dict like get_current_user() returns."""
    return {"id": uid, "username": f"user{uid}", "role": role}


class TestCheckProjectAccess:
    def test_none_user_denied(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(setup["project_id"], None, session_factory=db_factory)
        assert result is None

    def test_admin_always_allowed(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(
            setup["project_id"], _user(setup["admin_id"], "admin"),
            session_factory=db_factory,
        )
        assert result == "admin"

    def test_owner_has_all_roles(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        for min_role in ("viewer", "editor", "owner"):
            result = check_project_access(
                setup["project_id"], _user(setup["alice_id"]),
                min_role=min_role, session_factory=db_factory,
            )
            assert result == "owner", f"owner should satisfy min_role={min_role}"

    def test_viewer_satisfies_viewer(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(
            setup["project_id"], _user(setup["charlie_id"]),
            min_role="viewer", session_factory=db_factory,
        )
        assert result == "viewer"

    def test_viewer_denied_editor(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(
            setup["project_id"], _user(setup["charlie_id"]),
            min_role="editor", session_factory=db_factory,
        )
        assert result is None

    def test_no_access_denied(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(
            setup["project_id"], _user(setup["bob_id"]),
            session_factory=db_factory,
        )
        assert result is None

    def test_nonexistent_project(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(
            99999, _user(setup["alice_id"]),
            session_factory=db_factory,
        )
        assert result is None

    def test_default_min_role_is_viewer(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        result = check_project_access(
            setup["project_id"], _user(setup["charlie_id"]),
            session_factory=db_factory,
        )
        assert result == "viewer"


class TestRoleHierarchy:
    def test_hierarchy_values(self):
        from shyfem_ui.services.access_control import ROLE_HIERARCHY
        assert ROLE_HIERARCHY["owner"] > ROLE_HIERARCHY["editor"]
        assert ROLE_HIERARCHY["editor"] > ROLE_HIERARCHY["viewer"]

    def test_editor_satisfies_editor(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        # First give charlie editor access
        from shyfem_ui.services.sharing_service import SharingService
        svc = SharingService(session_factory=db_factory)
        svc.share_project(setup["project_id"], setup["charlie_id"], "editor")

        result = check_project_access(
            setup["project_id"], _user(setup["charlie_id"]),
            min_role="editor", session_factory=db_factory,
        )
        assert result == "editor"

    def test_editor_denied_owner(self, db_factory, setup):
        from shyfem_ui.services.access_control import check_project_access
        from shyfem_ui.services.sharing_service import SharingService
        svc = SharingService(session_factory=db_factory)
        svc.share_project(setup["project_id"], setup["charlie_id"], "editor")

        result = check_project_access(
            setup["project_id"], _user(setup["charlie_id"]),
            min_role="owner", session_factory=db_factory,
        )
        assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_access_control.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shyfem_ui.services.access_control'`

**Step 3: Write minimal implementation**

Create `shyfem_ui/services/access_control.py`:

```python
"""Access control helper for project-level permission checks."""

from shyfem_ui.services.sharing_service import SharingService

ROLE_HIERARCHY = {"owner": 3, "editor": 2, "viewer": 1}


def check_project_access(
    project_id: int,
    user: dict | None,
    min_role: str = "viewer",
    session_factory=None,
) -> str | None:
    """Check if user has at least min_role access to a project.

    Returns the user's actual role if sufficient, None if denied.
    Admins always get access (returns "admin").

    Args:
        project_id: The project to check access for.
        user: User dict from get_current_user() (or None).
        min_role: Minimum required role ("viewer", "editor", or "owner").
        session_factory: Optional SQLAlchemy session factory for testing.
    """
    if user is None:
        return None
    if user.get("role") == "admin":
        return "admin"

    svc = SharingService(session_factory=session_factory)
    actual_role = svc.get_user_role(project_id, user["id"])
    if actual_role is None:
        return None
    if ROLE_HIERARCHY.get(actual_role, 0) >= ROLE_HIERARCHY.get(min_role, 0):
        return actual_role
    return None
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_access_control.py -v`
Expected: 11 PASSED

**Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && git add shyfem_ui/services/access_control.py tests/test_access_control.py && git commit -m "feat: add access control helper with role hierarchy checks"
```

---

### Task 2: Admin page guard

**Files:**
- Modify: `shyfem_ui/pages/admin.py:111-122` (admin_server function start)
- Create: `tests/test_admin_guard.py`

**Step 1: Write the failing test**

Create `tests/test_admin_guard.py`:

```python
"""Tests for admin page access guard."""

import pytest


class TestAdminGuard:
    def test_admin_guard_function_allows_admin(self):
        from shyfem_ui.pages.admin import _check_admin_access
        result = _check_admin_access({"id": 1, "username": "admin", "role": "admin"})
        assert result is True

    def test_admin_guard_function_denies_user(self):
        from shyfem_ui.pages.admin import _check_admin_access
        result = _check_admin_access({"id": 2, "username": "user", "role": "user"})
        assert result is False

    def test_admin_guard_function_denies_none(self):
        from shyfem_ui.pages.admin import _check_admin_access
        result = _check_admin_access(None)
        assert result is False
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_admin_guard.py -v`
Expected: FAIL — `ImportError: cannot import name '_check_admin_access'`

**Step 3: Write minimal implementation**

Add the pure function to `shyfem_ui/pages/admin.py` below the existing `_active_badge` function (after line 69):

```python
def _check_admin_access(user: dict | None) -> bool:
    """Check if user has admin role. Returns False for None or non-admin users."""
    if user is None:
        return False
    return user.get("role") == "admin"
```

Then modify `admin_server` to use the guard. Add at the start of the function body (after `auth_service` parameter, before `users_data`):

```python
    # Admin role guard
    from shyfem_ui.middleware.session_auth import get_current_user
    current_user = get_current_user()
    if not _check_admin_access(current_user):
        @render.ui
        def user_summary():
            return ui.div(
                ui.h5("Access Denied", class_="text-danger"),
                ui.p("You must be an admin to view this page."),
            )

        @render.ui
        def user_table():
            return ui.div()

        return
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_admin_guard.py -v`
Expected: 3 PASSED

Then run full suite:
Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ --ignore-glob="tests/test_playwright_*" -x -q`
Expected: All passing (previous count + 3)

**Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && git add shyfem_ui/pages/admin.py tests/test_admin_guard.py && git commit -m "feat: add admin page access guard"
```

---

### Task 3: Enforcement in project_context, run.py, files.py

**Files:**
- Modify: `shyfem_ui/services/project_context.py:1-43`
- Modify: `shyfem_ui/pages/run.py:386-437` (_submit_job handler)
- Modify: `shyfem_ui/pages/files.py:287-314` (_handle_upload), `shyfem_ui/pages/files.py:372-411` (_register_delete_handler)
- Create: `tests/test_enforcement.py`

**Step 1: Write the failing tests**

Create `tests/test_enforcement.py`:

```python
"""Tests for access control enforcement at key endpoints."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models.project import Project
from shyfem_ui.models.user import ProjectPermission, User


@pytest.fixture
def db_factory():
    from shyfem_ui.models import project as _p, user as _u  # noqa: F841
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def setup(db_factory):
    db = db_factory()
    alice = User(username="alice", password_hash="x", role="user")
    bob = User(username="bob", password_hash="x", role="user")
    admin = User(username="admin", password_hash="x", role="admin")
    db.add_all([alice, bob, admin])
    db.flush()

    proj = Project(name="P1", work_dir="/tmp/p1", owner_id=alice.id)
    db.add(proj)
    db.flush()

    perm = ProjectPermission(project_id=proj.id, user_id=bob.id, role="viewer")
    db.add(perm)
    db.commit()

    data = {
        "alice_id": alice.id,
        "bob_id": bob.id,
        "admin_id": admin.id,
        "project_id": proj.id,
    }
    db.close()
    return data


def _user(uid, role="user"):
    return {"id": uid, "username": f"user{uid}", "role": role}


class TestProjectContextEnforcement:
    def test_load_with_access(self, db_factory, setup):
        from shyfem_ui.services.project_context import load_project_context
        # Owner should be able to load
        ctx = load_project_context(
            setup["project_id"],
            user=_user(setup["alice_id"]),
            session_factory=db_factory,
        )
        assert ctx is not None
        assert ctx["name"] == "P1"

    def test_load_denied(self, db_factory, setup):
        from shyfem_ui.services.project_context import load_project_context
        # Create a second user with no access
        db = db_factory()
        eve = User(username="eve", password_hash="x", role="user")
        db.add(eve)
        db.commit()
        eve_id = eve.id
        db.close()

        ctx = load_project_context(
            setup["project_id"],
            user=_user(eve_id),
            session_factory=db_factory,
        )
        assert ctx is None

    def test_load_admin_bypass(self, db_factory, setup):
        from shyfem_ui.services.project_context import load_project_context
        ctx = load_project_context(
            setup["project_id"],
            user=_user(setup["admin_id"], "admin"),
            session_factory=db_factory,
        )
        assert ctx is not None

    def test_load_no_user_returns_all(self, db_factory, setup):
        from shyfem_ui.services.project_context import load_project_context
        # When user is None (local mode), no filtering
        ctx = load_project_context(
            setup["project_id"],
            user=None,
            session_factory=db_factory,
        )
        assert ctx is not None

    def test_viewer_can_load(self, db_factory, setup):
        from shyfem_ui.services.project_context import load_project_context
        ctx = load_project_context(
            setup["project_id"],
            user=_user(setup["bob_id"]),
            session_factory=db_factory,
        )
        assert ctx is not None
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_enforcement.py -v`
Expected: FAIL — `TypeError: load_project_context() got an unexpected keyword argument 'user'`

**Step 3: Write minimal implementation**

Modify `shyfem_ui/services/project_context.py` to accept optional `user` and `session_factory` parameters:

```python
"""Load full project context from DB for active-project state."""

from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Grid, Project, ProjectFile, Simulation
from shyfem_ui.services.access_control import check_project_access


def load_project_context(
    project_id: int,
    user: dict | None = None,
    session_factory=None,
) -> dict | None:
    """Load project with its grids, simulations, and files as a plain dict.

    Returns None if the project_id does not exist or if the user
    lacks at least viewer access.

    Args:
        project_id: Project database ID.
        user: User dict from get_current_user(). None skips access check (local mode).
        session_factory: Optional session factory for testing.
    """
    # Access check (skip when user is None — local mode backward compat)
    if user is not None:
        role = check_project_access(project_id, user, min_role="viewer", session_factory=session_factory)
        if role is None:
            return None

    if session_factory:
        db = session_factory()
        try:
            return _load(db, project_id)
        finally:
            db.close()
    else:
        with db_session() as db:
            return _load(db, project_id)


def _load(db, project_id: int) -> dict | None:
    """Internal: load project data from an open session."""
    project = db.query(Project).filter_by(id=project_id).first()
    if project is None:
        return None
    grids = db.query(Grid).filter_by(project_id=project_id).all()
    sims = db.query(Simulation).filter_by(project_id=project_id).all()
    files = db.query(ProjectFile).filter_by(project_id=project_id).order_by(ProjectFile.filename).all()
    return {
        "id": project.id,
        "name": project.name,
        "work_dir": project.work_dir,
        "description": project.description,
        "grids": [
            {"name": g.name, "grd_file": g.grd_file, "bas_file": g.bas_file}
            for g in grids
        ],
        "simulations": [
            {"name": s.name, "str_file": s.str_file}
            for s in sims
        ],
        "files": [
            {
                "id": f.id,
                "filename": f.filename,
                "rel_path": f.rel_path,
                "file_type": f.file_type,
                "size_bytes": f.size_bytes,
            }
            for f in files
        ],
    }
```

Next, modify `shyfem_ui/pages/run.py` — add access check before job submission. In the `_submit_job` handler (line ~387), add at the very start of the function body:

```python
        # Access check: require editor role on active project
        if active_project is not None:
            proj = active_project.get()
            if proj is not None and _current_user is not None:
                from shyfem_ui.services.access_control import check_project_access
                if check_project_access(proj["id"], _current_user, min_role="editor") is None:
                    ui.notification_show("Permission denied: editor role required to submit jobs", type="error")
                    return
```

Next, modify `shyfem_ui/pages/files.py` — add access check in `_handle_upload` and `_register_delete_handler`. In `_handle_upload` (line ~287), after the `if proj is None: return` guard:

```python
        # Access check
        from shyfem_ui.middleware.session_auth import get_current_user
        from shyfem_ui.services.access_control import check_project_access
        user = get_current_user()
        if user is not None and check_project_access(proj["id"], user, min_role="editor") is None:
            ui.notification_show("Permission denied: editor role required to upload files", type="error")
            return
```

In `_register_delete_handler`, inside the `_do_delete` inner function (line ~399), add before `FileService.delete_file`:

```python
                    from shyfem_ui.middleware.session_auth import get_current_user
                    from shyfem_ui.services.access_control import check_project_access
                    user = get_current_user()
                    proj = active_project.get() if active_project else None
                    if user is not None and proj is not None:
                        if check_project_access(proj["id"], user, min_role="editor") is None:
                            ui.notification_show("Permission denied: editor role required to delete files", type="error")
                            ui.modal_remove()
                            return
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_enforcement.py -v`
Expected: 5 PASSED

Then run full suite:
Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ --ignore-glob="tests/test_playwright_*" -x -q`
Expected: All passing

**Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && git add shyfem_ui/services/project_context.py shyfem_ui/pages/run.py shyfem_ui/pages/files.py tests/test_enforcement.py && git commit -m "feat: enforce access control in project_context, run.py, and files.py"
```

---

### Task 4: Share button + modal in home.py

**Files:**
- Modify: `shyfem_ui/pages/home.py:267-317` (projects_list renderer), `shyfem_ui/pages/home.py:145-160` (home_server start)
- Create: `tests/test_sharing_ui.py`

**Step 1: Write the failing tests**

Create `tests/test_sharing_ui.py`:

```python
"""Tests for sharing UI pure functions."""

import pytest


class TestShouldShowShareButton:
    def test_owner_sees_share(self):
        from shyfem_ui.pages.home import _should_show_share_button
        project = {"id": 1, "owner_id": 10}
        user = {"id": 10, "role": "user"}
        assert _should_show_share_button(project, user) is True

    def test_admin_sees_share(self):
        from shyfem_ui.pages.home import _should_show_share_button
        project = {"id": 1, "owner_id": 10}
        user = {"id": 99, "role": "admin"}
        assert _should_show_share_button(project, user) is True

    def test_non_owner_no_share(self):
        from shyfem_ui.pages.home import _should_show_share_button
        project = {"id": 1, "owner_id": 10}
        user = {"id": 20, "role": "user"}
        assert _should_show_share_button(project, user) is False

    def test_none_user_no_share(self):
        from shyfem_ui.pages.home import _should_show_share_button
        project = {"id": 1, "owner_id": 10}
        assert _should_show_share_button(project, None) is False

    def test_none_owner_id_admin_sees(self):
        from shyfem_ui.pages.home import _should_show_share_button
        project = {"id": 1, "owner_id": None}
        user = {"id": 99, "role": "admin"}
        assert _should_show_share_button(project, user) is True

    def test_none_owner_id_user_no_share(self):
        from shyfem_ui.pages.home import _should_show_share_button
        project = {"id": 1, "owner_id": None}
        user = {"id": 20, "role": "user"}
        assert _should_show_share_button(project, user) is False


class TestBuildPermissionsTableData:
    def test_empty_list(self):
        from shyfem_ui.pages.home import _build_permissions_table_data
        assert _build_permissions_table_data([]) == []

    def test_formats_permissions(self):
        from shyfem_ui.pages.home import _build_permissions_table_data
        perms = [
            {"user_id": 2, "username": "bob", "display_name": "Bob", "role": "editor"},
            {"user_id": 3, "username": "charlie", "display_name": None, "role": "viewer"},
        ]
        result = _build_permissions_table_data(perms)
        assert len(result) == 2
        assert result[0]["username"] == "bob"
        assert result[0]["display_name"] == "Bob"
        assert result[0]["role"] == "editor"
        assert result[1]["display_name"] == "charlie"  # fallback to username
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_sharing_ui.py -v`
Expected: FAIL — `ImportError: cannot import name '_should_show_share_button'`

**Step 3: Write minimal implementation**

Add two pure functions to `shyfem_ui/pages/home.py` below `_safe_filename` (after line 32):

```python
def _should_show_share_button(project: dict, user: dict | None) -> bool:
    """Return True if user should see the Share button for this project.

    Only project owners and admins can share.
    """
    if user is None:
        return False
    if user.get("role") == "admin":
        return True
    return project.get("owner_id") == user.get("id")


def _build_permissions_table_data(permissions: list[dict]) -> list[dict]:
    """Format permission dicts for display in the share modal table."""
    return [
        {
            "user_id": p["user_id"],
            "username": p["username"],
            "display_name": p.get("display_name") or p["username"],
            "role": p["role"],
        }
        for p in permissions
    ]
```

Then modify the `projects_list` renderer to add a Share button for owners/admins. In the `projects_list` function (line ~267), replace the Actions td cell. The current code builds `ui.tags.td(...)` with Export and Clone links. Add a conditional Share link before Export:

In the loop that builds project rows, get the current user and check share visibility:

At the top of `home_server` (after `_is_server_mode`), add:
```python
    from shyfem_ui.middleware.session_auth import get_current_user as _get_user
    _current_user = _get_user()
```

In the `projects_list` renderer, change the Actions column to conditionally include a Share button:

```python
        for p in project_data:
            share_btn = None
            if _should_show_share_button(p, _current_user):
                share_btn = ui.input_action_link(
                    f"share_{p['id']}",
                    "Share",
                    class_="btn btn-sm btn-outline-success me-1",
                )

            rows.append(
                ui.tags.tr(
                    ui.tags.td(
                        ui.input_action_link(
                            f"project_{p['id']}",
                            p["name"],
                            class_="fw-bold",
                        )
                    ),
                    ui.tags.td(p["description"] or "-"),
                    ui.tags.td(ui.code(p["work_dir"], class_="small")),
                    ui.tags.td(
                        p["updated_at"].strftime("%Y-%m-%d %H:%M")
                        if p["updated_at"] else "-"
                    ),
                    ui.tags.td(
                        share_btn,
                        ui.input_action_link(
                            f"export_{p['id']}",
                            "Export",
                            class_="btn btn-sm btn-outline-secondary me-1",
                        ),
                        ui.input_action_link(
                            f"clone_{p['id']}",
                            "Clone",
                            class_="btn btn-sm btn-outline-secondary",
                        ),
                    ),
                )
            )
```

Add Share modal handler registration — after the existing `_register_clone_handlers` block, add share handlers:

```python
    # --- Share project handlers ---

    from shyfem_ui.services.sharing_service import SharingService

    @reactive.effect
    def _register_share_handlers():
        project_data = projects.get()
        for p in project_data:
            _make_share_handler(p["id"], p["name"])

    def _make_share_handler(pid: int, pname: str):
        @reactive.effect
        @reactive.event(input[f"share_{pid}"])
        def _share():
            _show_share_modal(pid, pname)

    def _show_share_modal(project_id: int, project_name: str):
        svc = SharingService()
        user_id = _current_user["id"] if _current_user else 0
        shareable = svc.list_shareable_users(project_id, exclude_user_id=user_id)
        perms = svc.list_permissions(project_id)
        perm_data = _build_permissions_table_data(perms)

        # Build user choices
        user_choices = {str(u["id"]): f"{u['username']} ({u['display_name'] or u['username']})" for u in shareable}

        # Build permissions table
        perm_rows = []
        for p in perm_data:
            perm_rows.append(
                ui.tags.tr(
                    ui.tags.td(p["display_name"]),
                    ui.tags.td(ui.span(p["role"], class_="badge bg-info")),
                    ui.tags.td(
                        ui.input_action_link(
                            f"unshare_{project_id}_{p['user_id']}",
                            "Remove",
                            class_="btn btn-sm btn-outline-danger",
                        ),
                    ),
                )
            )

        perm_table = None
        if perm_rows:
            perm_table = ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("User"),
                        ui.tags.th("Role"),
                        ui.tags.th(""),
                    )
                ),
                ui.tags.tbody(*perm_rows),
                class_="table table-sm",
            )
        else:
            perm_table = ui.p("No users shared with yet.", class_="text-muted small")

        user_select = None
        if user_choices:
            user_select = ui.div(
                ui.input_select("share_user_id", "User", choices=user_choices),
                ui.input_select(
                    "share_role", "Role",
                    choices={"viewer": "Viewer", "editor": "Editor"},
                ),
                ui.input_action_button(
                    f"confirm_share_{project_id}",
                    "Share",
                    class_="btn-primary mt-2",
                ),
            )
        else:
            user_select = ui.p("No users available to share with.", class_="text-muted small")

        m = ui.modal(
            ui.h6("Current Access"),
            perm_table,
            ui.hr(),
            ui.h6("Add User"),
            user_select,
            title=f"Share '{project_name}'",
            easy_close=True,
        )
        ui.modal_show(m)

        # Register confirm handler
        @reactive.effect
        @reactive.event(input[f"confirm_share_{project_id}"])
        def _do_share():
            uid = int(input.share_user_id())
            role = input.share_role()
            svc_inner = SharingService()
            svc_inner.share_project(project_id, uid, role)
            ui.notification_show("User added", type="message")
            ui.modal_remove()
            _refresh_projects()

        # Register unshare handlers
        for p in perm_data:
            _make_unshare_handler(project_id, project_name, p["user_id"])

    def _make_unshare_handler(project_id: int, project_name: str, target_user_id: int):
        @reactive.effect
        @reactive.event(input[f"unshare_{project_id}_{target_user_id}"])
        def _unshare():
            svc = SharingService()
            svc.unshare_project(project_id, target_user_id)
            ui.notification_show("Access removed", type="message")
            ui.modal_remove()
            _refresh_projects()
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_sharing_ui.py -v`
Expected: 8 PASSED

Then run full suite:
Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ --ignore-glob="tests/test_playwright_*" -x -q`
Expected: All passing

**Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && git add shyfem_ui/pages/home.py tests/test_sharing_ui.py && git commit -m "feat: add share button and modal for project sharing"
```

---

### Task 5: Update TODO_NEXT.md and wire user param into callers

**Files:**
- Modify: `shyfem_ui/TODO_NEXT.md`
- Modify: `shyfem_ui/pages/home.py` — pass `user` to `load_project_context` calls

**Step 1: Update load_project_context callers to pass user**

In `home.py`, every call to `load_project_context(project_id)` should pass the current user. Search for all calls:

1. `_activate_project` (line ~554): Change to `load_project_context(project_id, user=_current_user)`
2. `_create_tutorial_project` (line ~532): Change to `load_project_context(project_id, user=_current_user)`
3. `_do_import_grid` (line ~698): Change to `load_project_context(project_id, user=_current_user)`
4. `_do_export` (line ~755): Change to `load_project_context(project_id, user=_current_user)`
5. `_do_clone` (line ~801): Change to `load_project_context(project_id, user=_current_user)`

**Step 2: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ --ignore-glob="tests/test_playwright_*" -x -q`
Expected: All passing

**Step 3: Update TODO_NEXT.md**

Add Phase 46 entry under the Round 3 section:

```markdown
### Phase 46: Sharing UI + Access Control [COMPLETE]
- `check_project_access()` helper with role hierarchy (owner > editor > viewer)
- Admin page guard (non-admins see "Access denied")
- Enforcement: project_context load, job submit, file upload/delete
- Share modal on project cards (owners/admins only)
- ~30 tests
```

**Step 4: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && git add shyfem_ui/pages/home.py shyfem_ui/TODO_NEXT.md && git commit -m "feat: wire user param into load_project_context callers, update TODO"
```

---

## Test Summary

| Task | Test File | Tests |
|------|-----------|-------|
| 1: Access control helper | `tests/test_access_control.py` | 11 |
| 2: Admin guard | `tests/test_admin_guard.py` | 3 |
| 3: Enforcement | `tests/test_enforcement.py` | 5 |
| 4: Sharing UI | `tests/test_sharing_ui.py` | 8 |
| **Total** | | **~27** |

## Dependency Graph

```
Task 1 (access control helper)
  ├── Task 2 (admin guard) — independent
  ├── Task 3 (enforcement) — depends on Task 1
  └── Task 4 (share modal) — independent of Tasks 2-3
Task 5 (wiring + TODO) — depends on Tasks 1-4
```
