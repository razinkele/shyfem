# User Management System Design

**Date:** 2026-03-03
**Scope:** Required emails, per-user filesystem directories, simulation completion notifications

---

## Background

The SHYFEM UI already has a session-based auth system (Argon2 passwords, SQLite, admin-managed accounts). Three things are missing for a shared server deployment:

1. Email is stored but optional — no enforcement, no use
2. All users share a single `work_dir`; no per-user filesystem isolation
3. No notifications when simulations finish or fail

This design adds all three with minimal changes to the existing architecture.

---

## Deployment Context

- **Shared server** (e.g. `laguna.ku.lt`): multiple researchers log in remotely
- **Admin-only account creation**: admins create every account; no self-registration
- **Admin-only password management**: only admins can reset passwords
- **Approach B (focused extension)**: slot into existing SQLAlchemy + Shiny + job queue system

---

## Section 1: User Model & Per-User Directories

### Model Changes

`email` becomes non-nullable (required). No new DB column for `home_dir` — it is a computed `@property`:

```python
@property
def home_dir(self) -> Path:
    return Path(config.user_data_root) / self.username
```

### Directory Creation

`AuthService.create_user()` calls `home_dir.mkdir(parents=True, exist_ok=True)` after persisting the user record. If the filesystem path is not writable, a `PermissionError` is raised before committing to the DB — no partial state.

### Project Default Path

New projects created by a user default `work_dir` to:

```
{user.home_dir}/projects/{project_name}/
```

Existing projects are untouched.

### Config

New field `user_data_root` (default: `/data/shyfem`), overridable via `SHYFEM_UI_USER_DATA_ROOT` env var.

---

## Section 2: NotificationService

### New File: `services/notification_service.py`

```
NotificationService
├── notify_job_success(user: User, job: Job) → None
└── notify_job_failed(user: User, job: Job) → None
```

Both methods are synchronous; called via `asyncio.run_in_executor` from async job queue handlers to avoid blocking the event loop.

Sending uses Python stdlib `smtplib` + `ssl.create_default_context()`. If `SHYFEM_UI_SMTP_HOST` is not configured, the service logs a warning and returns — the system works without SMTP (development/local installs).

SMTP errors are caught, logged at WARNING level, and not re-raised — a notification failure must never crash a simulation job.

### SMTP Config (`.env`)

```
SHYFEM_UI_SMTP_HOST=smtp.example.com
SHYFEM_UI_SMTP_PORT=587
SHYFEM_UI_SMTP_USER=noreply@example.com
SHYFEM_UI_SMTP_PASSWORD=...
SHYFEM_UI_SMTP_FROM=SHYFEM UI <noreply@example.com>
```

### Email Templates

Plain-text Jinja2 templates in `shyfem_ui/templates/email/`:

**`job_success.txt`**
- Subject: `[SHYFEM] Simulation finished: {job_name}`
- Body: job name, duration, output directory path

**`job_failed.txt`**
- Subject: `[SHYFEM] Simulation failed: {job_name}`
- Body: job name, error summary (last 10 lines of stderr)

### Job Queue Integration

`local_job_queue.py` and `celery_job_queue.py` call `notification_service.notify_job_success/failed(user, job)` in the job completion handler. The `user` is resolved from `job.owner_id` via a DB lookup.

---

## Section 3: Admin Panel Updates

### 1. Create User Form

- `email` field added as required
- Basic `@` format validation client-side; uniqueness checked server-side
- Computed home directory path (`/data/shyfem/{username}`) shown as read-only preview
- If directory creation fails (permission denied, disk full): error shown inline, user record not saved

### 2. User List Table

Two new columns:
- **Email** — stored address
- **Home Directory** — path with disk icon; if directory missing on disk, shown in amber with "Create now" button

### 3. Send Test Email Button

Per-user row action (admin-only). Sends a short plain-text test email to the user's address. Shows success toast or inline SMTP error. Lets admins verify email routing without waiting for a simulation.

---

## Section 4: Testing (~20 new tests → ~1322 total)

### `tests/test_user_model.py` (~5 tests)

- `test_email_required` — missing email raises DB integrity error
- `test_email_unique` — duplicate email raises integrity error
- `test_home_dir_property` — returns `Path({user_data_root}/{username})`
- `test_create_user_creates_directory` — directory created on disk
- `test_create_user_directory_exists_ok` — pre-existing directory is fine

### `tests/test_notification_service.py` (~8 tests)

- `test_no_smtp_config_skips_silently` — no host → no exception, logs warning
- `test_notify_success_sends_email` — mocked SMTP, subject/body contain job name
- `test_notify_failed_sends_email` — error summary in body
- `test_notify_failed_truncates_long_stderr` — last 10 lines only
- `test_smtp_failure_logs_and_does_not_raise` — SMTP error logged, not propagated
- `test_template_renders_output_path` — home dir path in success email
- `test_job_queue_calls_notify_on_success` — integration with mocked notification service
- `test_job_queue_calls_notify_on_failure` — same for failure path

### `tests/test_admin_user_management.py` (~7 tests)

- `test_create_user_requires_email` — form rejects missing email
- `test_create_user_invalid_email` — rejects `notanemail`
- `test_create_user_duplicate_email` — inline error on duplicate
- `test_create_user_directory_permission_error` — filesystem error handled gracefully
- `test_send_test_email_success` — test email action triggers notification
- `test_send_test_email_smtp_failure` — SMTP error shown inline, no crash
- `test_legacy_user_missing_directory_shown_in_amber` — legacy accounts flagged in table

---

## Out of Scope

- Self-service password change (admin-only password management)
- User self-registration (admin-only account creation)
- Email verification on account creation
- Two-factor authentication
- Audit logging
- Directory quota enforcement
- OAuth / OIDC
