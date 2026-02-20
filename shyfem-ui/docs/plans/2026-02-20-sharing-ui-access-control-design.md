# Sharing UI + Access Control Design

**Date:** 2026-02-20
**Status:** Approved
**Depends on:** Phase 45 (User Management) complete, 949 tests passing

## Problem

Phase 45 created the data models (User, ProjectPermission) and services (AuthService, SharingService) but no UI for sharing and zero access control enforcement. Any authenticated user can load any project context, submit jobs on any project, and upload/delete files regardless of ownership or permissions.

## Approach: Access Control Helper + Inline Checks

Single `check_project_access()` helper function called inline at each enforcement point. No decorators, no middleware-level enforcement. Simple, explicit, testable.

## Access Control Helper

New `services/access_control.py`:

```python
ROLE_HIERARCHY = {"owner": 3, "editor": 2, "viewer": 1}

def check_project_access(project_id: int, user: dict, min_role: str = "viewer") -> str | None:
    """Check if user has at least min_role access to a project.

    Returns the user's actual role if sufficient, None if denied.
    Admins always get access (returns "admin").
    """
    if user is None:
        return None
    if user.get("role") == "admin":
        return "admin"
    actual_role = SharingService().get_user_role(project_id, user["id"])
    if actual_role is None:
        return None
    if ROLE_HIERARCHY.get(actual_role, 0) >= ROLE_HIERARCHY.get(min_role, 0):
        return actual_role
    return None
```

## Enforcement Points

| Location | Min Role | Denied Behavior |
|----------|----------|-----------------|
| `project_context.py` load | viewer | Returns None |
| `run.py` job submit | editor | Notification error |
| `files.py` upload | editor | Notification error |
| `files.py` delete | editor | Notification error |
| `admin.py` server init | admin (system role) | "Access denied" message |
| `home.py` Share button | owner or admin | Button not rendered |

## Share Modal (in home.py)

- "Share" button on project cards for owners/admins only
- Modal contents:
  - User dropdown (from `SharingService.list_shareable_users()`)
  - Role select: Viewer / Editor
  - "Share" confirm button
  - Current permissions table with "Remove" action links
- Refresh permissions list after share/unshare

## Admin Page Guard

Check `get_current_user()["role"] == "admin"` at start of `admin_server()`. Non-admins see "Access denied" instead of user table. Tab remains visible (Shiny static layout constraint).

## Backward Compatibility

- Local mode: synthetic admin user (role="admin") bypasses all checks
- Unowned projects (owner_id=None): visible to admins only (existing behavior)

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `services/access_control.py` | Create | `check_project_access()` helper |
| `services/project_context.py` | Modify | Add access check to `load_project_context()` |
| `pages/run.py` | Modify | Check editor role before job submit |
| `pages/files.py` | Modify | Check editor role before upload/delete |
| `pages/admin.py` | Modify | Admin role guard |
| `pages/home.py` | Modify | Share button + modal |
| `tests/test_access_control.py` | Create | Access control helper tests |
| `tests/test_sharing_ui.py` | Create | Share modal pure function tests |
| `tests/test_enforcement.py` | Create | Permission enforcement tests |

## Estimated Tests: ~30

- Access control helper: ~12 (role combos, admin bypass, None user, local mode)
- Sharing UI functions: ~8 (button visibility, modal data builders)
- Enforcement integration: ~10 (project_context, run.py, files.py checks)

## Dependency Order

```
1. Access control helper + tests (independent)
2. Admin page guard (depends on 1)
3. Enforcement in project_context, run.py, files.py (depends on 1)
4. Share button + modal in home.py (depends on 1)
5. TODO_NEXT.md update
```

Tasks 2, 3, 4 are independent of each other after task 1.
