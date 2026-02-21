# User Management Design

**Date:** 2026-02-20
**Status:** COMPLETE (2026-02-21)
**Depends on:** Phase 44 (File Management UI) complete, 851 tests passing
**Result:** 98 new tests, 949 total passing. Merged to main.

## Problem

SHYFEM-UI has only HTTP Basic Auth with a single shared credential. No user concept exists — all projects and jobs are visible to everyone. Server deployments with multiple researchers need per-user project isolation, role-based access, and secure session management.

## Requirements

- Session-based login (login form -> server-side session cookie)
- Two roles: admin (manage users, see all) and user (own projects/jobs only)
- Private projects by default + explicit sharing with other users
- Admin-only user creation (no self-registration)
- Backward compatible: local mode unchanged, server mode upgrades smoothly

## Approach: ASGI Middleware + Shiny Conditional UI

Auth validation in ASGI middleware (reads cookie, injects user into scope). Shiny renders login form when no user present, main app when authenticated. Cookie set via JS message handler on successful login.

## Database Models

### User

```
users:
  id (PK, auto-increment)
  username (VARCHAR 64, UNIQUE, NOT NULL)
  display_name (VARCHAR 128)
  email (VARCHAR 255, UNIQUE, nullable)
  password_hash (VARCHAR 255, NOT NULL)  -- bcrypt via passlib
  role (VARCHAR 16, NOT NULL, default 'user')  -- 'admin' or 'user'
  is_active (BOOLEAN, default True)
  created_at, updated_at (DateTime)
```

### AuthSession (server-side sessions)

```
auth_sessions:
  id (PK)
  token (VARCHAR 64, UNIQUE, indexed)  -- secrets.token_hex(32)
  user_id (FK -> users.id)
  created_at (DateTime)
  expires_at (DateTime)
  ip_address (VARCHAR 45, nullable)
```

### ProjectPermission (sharing)

```
project_permissions:
  id (PK)
  project_id (FK -> projects.id)
  user_id (FK -> users.id)
  role (VARCHAR 16)  -- 'viewer' or 'editor'
  created_at (DateTime)
  UNIQUE(project_id, user_id)
```

### Modified Existing Tables

- `projects`: add `owner_id` (FK -> users.id, nullable for migration)
- `jobs`: add `user_id` (FK -> users.id, nullable for migration)

## Component 1: AuthService

New `services/auth_service.py` — pure functions + DB operations:

| Function | Purpose |
|----------|---------|
| `hash_password(plain)` | bcrypt hash via passlib |
| `verify_password(plain, hash)` | Timing-safe comparison |
| `create_session(user_id, ip)` | Generate token, store in DB, return token |
| `validate_session(token)` | Check DB + expiry, return User or None |
| `cleanup_expired_sessions()` | Delete expired sessions |
| `create_user(username, password, role, email)` | Create user with hashed password |
| `update_user(user_id, ...)` | Update display_name, email, role |
| `deactivate_user(user_id)` | Set is_active=False |
| `reset_password(user_id, new_password)` | Update password_hash |
| `list_users()` | All users (admin only) |
| `get_user(user_id)` | Single user by ID |
| `authenticate(username, password)` | Verify credentials, return User or None |

## Component 2: SessionAuthMiddleware

ASGI middleware replacing BasicAuthMiddleware:

1. Read `shyfem_session` cookie from request headers
2. Call `AuthService.validate_session(token)`
3. If valid: `scope["user"] = {"id": ..., "username": ..., "role": ...}`
4. If invalid/missing: `scope["user"] = None`
5. Always pass through (no blocking — Shiny handles conditional rendering)

WebSocket: Read cookie from initial handshake headers.

Local mode: Skip middleware, always inject synthetic admin user.

## Component 3: Login Flow (Shiny-side)

In `app.py`, wrap main UI in conditional:
- `scope["user"] is None` → render login form (username, password, submit)
- `scope["user"]` present → render normal app with navigation

Login submission:
1. Shiny server receives credentials via `input.login_submit()`
2. Calls `AuthService.authenticate(username, password)`
3. If valid: `AuthService.create_session()` → send JS `set_cookie` message → page reloads
4. If invalid: show error notification

Logout: Navbar button → JS clears cookie → page reloads.

JS handler (registered once):
```javascript
Shiny.addCustomMessageHandler('set_cookie', function(msg) {
    document.cookie = msg.name + '=' + msg.value + '; path=/; max-age=' + msg.max_age + '; SameSite=Strict; Secure';
    if (msg.reload) location.reload();
});
Shiny.addCustomMessageHandler('clear_cookie', function(msg) {
    document.cookie = msg.name + '=; path=/; max-age=0';
    if (msg.reload) location.reload();
});
```

## Component 4: Admin Panel

New `pages/admin.py` — visible only when `user.role == 'admin'`:

### Sidebar
- Total user count
- "Create User" button → modal (username, password, display name, email, role dropdown)

### Main Panel
- User table: username, display name, email, role badge, active status, created date
- Per-row actions: Reset Password, Toggle Active, Change Role
- Confirmation modals for destructive actions

## Component 5: Project Ownership & Sharing

### Project Creation
`owner_id` set to `current_user.id`.

### Project Listing

**Regular user:**
```python
projects = db.query(Project).filter(
    or_(
        Project.owner_id == user_id,
        Project.id.in_(
            db.query(ProjectPermission.project_id)
            .filter(ProjectPermission.user_id == user_id)
        )
    )
)
```

**Admin:** All projects visible.

### Sharing UI
On Dashboard project card (owner only): "Share" button → modal with:
- User search/select dropdown
- Role select (viewer / editor)
- Current shares list with remove button

### Permission Enforcement
- Viewer: can see project, browse files, view STR, view job outputs
- Editor: all viewer permissions + run jobs, modify STR, upload/delete files
- Owner: all editor permissions + share, delete project

### Job Ownership
`Job.user_id` set on submission. Jobs filtered by `user_id` (replaces `session_id` filtering). Admins see all. "All Jobs" toggle remains for admin use.

## Component 6: Alembic Migration

Single migration adding:
1. `users` table
2. `auth_sessions` table
3. `project_permissions` table
4. `projects.owner_id` column (nullable FK)
5. `jobs.user_id` column (nullable FK)
6. Default admin user (from config: `default_admin_username` / `default_admin_password`)

## Config Changes

```python
# Session management
auth_session_ttl_hours: int = 24  # Cookie lifetime

# Default admin (created on first run)
default_admin_username: str = "admin"
default_admin_password: str = ""  # Required in server mode
```

Environment variables:
```bash
SHYFEM_UI_AUTH_SESSION_TTL_HOURS=24
SHYFEM_UI_DEFAULT_ADMIN_USERNAME=admin
SHYFEM_UI_DEFAULT_ADMIN_PASSWORD=changeme
```

## Backward Compatibility

- **Local mode:** Auth disabled. No login form. Synthetic admin user injected with `scope["user"] = {"id": 0, "username": "local", "role": "admin"}`. All features work as before.
- **Server mode migration:** On first startup, creates admin user from `default_admin_username` / `default_admin_password`. Existing projects get `owner_id = NULL` (visible to admins, can be claimed).

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `models/user.py` | Create | User, AuthSession, ProjectPermission models |
| `services/auth_service.py` | Create | Password hashing, session management, user CRUD |
| `middleware/session_auth.py` | Create | SessionAuthMiddleware |
| `pages/admin.py` | Create | Admin panel for user management |
| `pages/__init__.py` | Modify | Add admin export |
| `app.py` | Modify | Login UI, cookie JS handlers, middleware swap, admin tab |
| `config.py` | Modify | New auth config fields |
| `models/project.py` | Modify | Add owner_id to Project, user_id to Job |
| `pages/home.py` | Modify | Filter projects by ownership |
| `pages/run.py` | Modify | Set user_id on jobs, filter by user |
| `services/project_context.py` | Modify | Access control checks |
| `migrations/versions/xxx_add_users.py` | Create | Alembic migration |
| `tests/test_auth_service.py` | Create | Auth service tests |
| `tests/test_session_auth_middleware.py` | Create | Middleware tests |
| `tests/test_admin_page.py` | Create | Admin panel tests |
| `tests/test_project_ownership.py` | Create | Ownership + sharing tests |

## Estimated Test Count

~60-70 new tests:
- AuthService: ~20 (hash, verify, session CRUD, user CRUD, authenticate, cleanup)
- SessionAuthMiddleware: ~10 (valid/invalid cookie, no cookie, expired, WS, local mode)
- Admin page: ~10 (list users, create, deactivate, reset password, role change)
- Project ownership: ~12 (create with owner, list filtered, share, permission enforce)
- Job ownership: ~5 (submit with user_id, list filtered, admin sees all)
- Login flow: ~5 (valid login, invalid, logout, session expiry)

## Dependency Order

```
1. Models (User, AuthSession, ProjectPermission) + Migration
2. AuthService (depends on models)
3. SessionAuthMiddleware (depends on AuthService)
4. Login UI + cookie JS (depends on middleware)
5. Admin panel (depends on AuthService + login)
6. Project ownership + query filtering (depends on models)
7. Job ownership + query filtering (depends on models)
8. Sharing UI (depends on ProjectPermission + admin panel)
```

Tasks 1-4 are sequential (each depends on previous).
Tasks 5, 6, 7, 8 are independent of each other (can be done in any order after 1-4).
