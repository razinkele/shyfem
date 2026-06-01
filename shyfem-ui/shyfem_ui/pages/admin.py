"""Admin panel for user management.

Provides a Shiny module for listing users, creating new users,
resetting passwords, toggling active status, and promoting/demoting roles.
"""

import logging
import re

from shiny import module, reactive, render, ui

from shyfem_ui.config import Config
from shyfem_ui.models.user import ROLE_ADMIN, ROLE_TUTORIAL, ROLE_USER
from shyfem_ui.services.auth_service import AuthService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pure functions (testable without Shiny runtime)
# ---------------------------------------------------------------------------

_VALID_ROLES = {ROLE_ADMIN, ROLE_USER, ROLE_TUTORIAL}


def _build_user_table_data(users: list[dict]) -> list[dict]:
    """Convert user dicts to table row dicts.

    Fills in defaults for missing optional fields.
    """
    return [
        {
            "id": u["id"],
            "username": u["username"],
            "display_name": u.get("display_name") or u["username"],
            "email": u.get("email") or "-",
            "role": u["role"],
            "is_active": u.get("is_active", True),
        }
        for u in users
    ]


def _validate_create_user_form(
    username: str, password: str, role: str, email: str | None = None
) -> list[str]:
    """Validate user creation form inputs.

    Args:
        username: Login name.
        password: Plaintext password.
        role: User role.
        email: Email address. Required for non-tutorial accounts.

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []
    if not username or not username.strip():
        errors.append("Username is required")
    if username and username.strip():
        if not re.match(r"^[a-zA-Z0-9._-]{1,64}$", username.strip()):
            errors.append(
                "Username may only contain letters, digits, dots, hyphens, and underscores (1-64 characters)"
            )
        elif ".." in username:
            errors.append("Username must not contain consecutive dots")
    if not password:
        errors.append("Password is required")
    elif len(password) < 8:
        errors.append("Password must be at least 8 characters")
    if role not in _VALID_ROLES:
        errors.append(f"Role must be one of: {', '.join(sorted(_VALID_ROLES))}")
    # Email required for non-tutorial accounts
    if role != ROLE_TUTORIAL:
        if not email or not email.strip():
            errors.append("Email is required")
        elif "@" not in email or "." not in email.split("@")[-1]:
            errors.append("Email address is not valid")
    return errors


def _role_badge(role: str) -> str:
    """Return HTML badge for a role."""
    cls = "bg-danger" if role == ROLE_ADMIN else "bg-primary"
    return f'<span class="badge {cls}">{role}</span>'


def _active_badge(is_active: bool) -> str:
    """Return HTML badge for active status."""
    if is_active:
        return '<span class="badge bg-success">Active</span>'
    return '<span class="badge bg-secondary">Inactive</span>'


def _check_admin_access(user: dict | None) -> bool:
    """Check if user has admin role. Returns False for None or non-admin users."""
    if user is None:
        return False
    return user.get("role") == ROLE_ADMIN


# ---------------------------------------------------------------------------
# Shiny UI module
# ---------------------------------------------------------------------------


@module.ui
def admin_ui() -> ui.Tag:
    """Admin panel UI."""
    return ui.div(
        ui.h3("Administration"),
        ui.hr(),
        ui.navset_tab(
            ui.nav_panel(
                "Users",
                ui.div(
                    ui.row(
                        ui.column(
                            3,
                            ui.div(
                                ui.output_ui("user_summary"),
                                ui.hr(),
                                ui.input_action_button(
                                    "create_user_btn", "Create User", class_="btn-primary w-100"
                                ),
                                class_="card p-3",
                            ),
                        ),
                        ui.column(
                            9,
                            ui.div(
                                ui.output_ui("user_table"),
                                class_="card p-3",
                            ),
                        ),
                    ),
                    class_="mt-3",
                ),
            ),
            ui.nav_panel(
                "Logs",
                ui.div(
                    ui.row(
                        ui.column(
                            3,
                            ui.div(
                                ui.h6("Filters"),
                                ui.input_select(
                                    "log_user_filter",
                                    "User",
                                    choices={"": "All users"},
                                ),
                                ui.input_select(
                                    "log_action_filter",
                                    "Action",
                                    choices={"": "All actions"},
                                ),
                                ui.input_action_button(
                                    "log_refresh_btn",
                                    "Refresh",
                                    class_="btn-outline-secondary w-100 mt-2",
                                ),
                                ui.hr(),
                                ui.output_ui("log_summary"),
                                class_="card p-3",
                            ),
                        ),
                        ui.column(
                            9,
                            ui.div(
                                ui.output_ui("log_table"),
                                ui.div(
                                    ui.input_action_button(
                                        "log_prev_btn",
                                        "Previous",
                                        class_="btn-sm btn-outline-secondary me-2",
                                    ),
                                    ui.output_ui("log_page_info"),
                                    ui.input_action_button(
                                        "log_next_btn",
                                        "Next",
                                        class_="btn-sm btn-outline-secondary ms-2",
                                    ),
                                    class_="d-flex align-items-center justify-content-center mt-3",
                                ),
                                class_="card p-3",
                            ),
                        ),
                    ),
                    class_="mt-3",
                ),
            ),
            id="admin_tabs",
        ),
    )


# ---------------------------------------------------------------------------
# Shiny server module
# ---------------------------------------------------------------------------


@module.server
def admin_server(
    input,
    output,
    session,
    config: Config,
    auth_service: AuthService,
    user_role=None,
    audit_service=None,
    current_user=None,
) -> None:
    """Admin panel server logic.

    ``current_user`` is the server-validated WS identity resolver (returns the
    user dict bound to the ``_wsauth`` token, or None). It — NOT the
    client-pushed ``user_role()`` signal — is the authorization source for
    every admin mutation.
    """
    from shyfem_ui.middleware.session_auth import get_current_user

    def _audit(action: str, detail: str | None = None):
        """Write an audit log entry for the current admin user."""
        if audit_service is not None:
            user = get_current_user()
            username = user["username"] if user else "unknown"
            audit_service.log(username=username, action=action, detail=detail)

    def _is_admin() -> bool:
        """Authorize admin access from the SERVER-VALIDATED WS identity.

        Authorization must derive from ``current_user()`` (the user dict bound
        server-side to the ``_wsauth`` token) or, in the HTTP scope, from
        ``get_current_user()``. It must NEVER trust ``user_role()`` — that
        signal is set by the browser (``Shiny.setInputValue('current_user_role',
        ...)``) and is trivially spoofable from the console, so using it as an
        authorization boundary lets any authenticated user self-promote to
        admin. ``user_role()`` remains only a cosmetic hint for rendering.
        """
        if current_user is not None:
            try:
                if _check_admin_access(current_user()):
                    return True
            except Exception:
                logger.debug("current_user() not yet available", exc_info=True)
        return _check_admin_access(get_current_user())

    # Reactive value holding user list (always defined so render functions can reference it)
    users_data: reactive.Value[list[dict]] = reactive.value([])

    # Track which user IDs have already had their action handlers registered.
    # Prevents duplicate effects when _register_all_user_actions re-runs on refresh.
    _registered_user_ids: set[int] = set()

    # Load users whenever admin status becomes available
    @reactive.effect
    def _load_users():
        if _is_admin():
            users_data.set(auth_service.list_users())

    def _refresh():
        users_data.set(auth_service.list_users())

    # ------------------------------------------------------------------
    # Summary card
    # ------------------------------------------------------------------

    @render.ui
    def user_summary():
        if not _is_admin():
            return ui.div(
                ui.h5("Access Denied", class_="text-danger"),
                ui.p("You must be an admin to view this page."),
            )
        users = users_data.get()
        total = len(users)
        admins = sum(1 for u in users if u["role"] == ROLE_ADMIN)
        active = sum(1 for u in users if u.get("is_active", True))
        return ui.div(
            ui.h6("Summary"),
            ui.p(f"Total users: {total}"),
            ui.p(f"Admins: {admins}"),
            ui.p(f"Active: {active}"),
        )

    # ------------------------------------------------------------------
    # User table
    # ------------------------------------------------------------------

    @render.ui
    def user_table():
        if not _is_admin():
            return ui.div()
        users = users_data.get()
        if not users:
            return ui.p("No users found.", class_="text-muted")

        rows_data = _build_user_table_data(users)
        rows = []
        for u in rows_data:
            # Home directory: N/A for tutorial users
            if u["role"] == ROLE_TUTORIAL:
                home_dir_text = "N/A"
            else:
                home_dir_text = str(config.user_data_root / u["username"])
            rows.append(
                ui.tags.tr(
                    ui.tags.td(u["username"]),
                    ui.tags.td(u["display_name"]),
                    ui.tags.td(u["email"]),
                    ui.tags.td(ui.HTML(_role_badge(u["role"]))),
                    ui.tags.td(ui.HTML(_active_badge(u["is_active"]))),
                    ui.tags.td(home_dir_text, style="font-size:0.8em;word-break:break-all;"),
                    ui.tags.td(
                        ui.input_action_link(
                            f"reset_pw_{u['id']}",
                            "Reset PW",
                            class_="btn btn-sm btn-outline-warning me-1",
                        ),
                        ui.input_action_link(
                            f"toggle_active_{u['id']}",
                            "Deactivate" if u["is_active"] else "Activate",
                            class_="btn btn-sm btn-outline-secondary me-1",
                        ),
                        ui.input_action_link(
                            f"toggle_role_{u['id']}",
                            "Demote" if u["role"] == ROLE_ADMIN else "Promote",
                            class_="btn btn-sm btn-outline-info me-1",
                        ),
                        ui.input_action_link(
                            f"send_test_email_{u['id']}",
                            "Test Email",
                            class_="btn btn-sm btn-outline-primary me-1",
                        ),
                        ui.input_action_link(
                            f"delete_user_{u['id']}",
                            "Delete",
                            class_="btn btn-sm btn-outline-danger",
                        ),
                    ),
                )
            )

        return ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(
                    ui.tags.th("Username"),
                    ui.tags.th("Display Name"),
                    ui.tags.th("Email"),
                    ui.tags.th("Role"),
                    ui.tags.th("Status"),
                    ui.tags.th("Home Dir"),
                    ui.tags.th("Actions"),
                )
            ),
            ui.tags.tbody(*rows),
            class_="table table-hover",
        )

    # ------------------------------------------------------------------
    # Dynamic action handlers for user table buttons
    # ------------------------------------------------------------------

    def _register_user_actions(user_id: int, username: str, email: str | None = None):
        """Register action handlers for a specific user row.

        Safe to call multiple times — subsequent calls for an already-registered
        user_id are silently ignored, preventing handler accumulation across refreshes.
        """
        if user_id in _registered_user_ids:
            return
        _registered_user_ids.add(user_id)

        def _get_user() -> dict | None:
            return next((u for u in users_data.get() if u["id"] == user_id), None)

        @reactive.effect
        @reactive.event(input[f"reset_pw_{user_id}"])
        def _reset_pw():
            # Show a modal to enter new password
            m = ui.modal(
                ui.input_password("reset_pw_value", "New Password"),
                title=f"Reset Password for {username}",
                easy_close=True,
                footer=ui.div(
                    ui.input_action_button(
                        f"confirm_reset_pw_{user_id}",
                        "Reset",
                        class_="btn-warning",
                    ),
                    ui.modal_button("Cancel"),
                ),
            )
            ui.modal_show(m)

        @reactive.effect
        @reactive.event(input[f"confirm_reset_pw_{user_id}"])
        def _do_reset_pw():
            if not _is_admin():
                ui.notification_show("Administrator access required.", type="error", duration=6)
                return
            new_pw = input.reset_pw_value() or ""
            if len(new_pw) < 8:
                ui.notification_show(
                    "Password must be at least 8 characters", type="error", duration=6
                )
                return
            try:
                auth_service.reset_password(user_id, new_pw)
                _audit("reset_password", f"target={username}")
                ui.modal_remove()
                ui.notification_show(f"Password reset for '{username}'", type="message", duration=4)
            except Exception as e:
                logger.exception("Failed to reset password for user %d", user_id)
                ui.notification_show(f"Error: {e}", type="error", duration=6)

        @reactive.effect
        @reactive.event(input[f"toggle_active_{user_id}"])
        def _toggle_active():
            if not _is_admin():
                ui.notification_show("Administrator access required.", type="error", duration=6)
                return
            user = _get_user()
            if user is None:
                return
            try:
                new_active = not user.get("is_active", True)
                auth_service.update_user(user_id, is_active=new_active)
                status = "activated" if new_active else "deactivated"
                _audit(f"user_{status}", f"target={username}")
                ui.notification_show(f"User '{username}' {status}", type="message", duration=4)
                _refresh()
            except Exception as e:
                logger.exception("Failed to toggle active for user %d", user_id)
                ui.notification_show(f"Error: {e}", type="error", duration=6)

        @reactive.effect
        @reactive.event(input[f"toggle_role_{user_id}"])
        def _toggle_role():
            if not _is_admin():
                ui.notification_show("Administrator access required.", type="error", duration=6)
                return
            user = _get_user()
            if user is None:
                return
            role = user["role"]
            try:
                if role == ROLE_ADMIN:
                    new_role = "user"
                elif role == ROLE_USER:
                    new_role = "admin"
                else:  # tutorial or unknown
                    new_role = "user"  # promote tutorial to user first
                auth_service.update_user(user_id, role=new_role)
                action = "demoted to user" if new_role == ROLE_USER else "promoted to admin"
                _audit("change_role", f"target={username}, new_role={new_role}")
                ui.notification_show(f"User '{username}' {action}", type="message", duration=4)
                _refresh()
            except Exception as e:
                logger.exception("Failed to toggle role for user %d", user_id)
                ui.notification_show(f"Error: {e}", type="error", duration=6)

        @reactive.effect
        @reactive.event(input[f"send_test_email_{user_id}"])
        def _send_test_email():
            """Send a test notification email to this user."""
            from shyfem_ui.services.notification_service import NotificationService

            if not _is_admin():
                ui.notification_show("Administrator access required.", type="error", duration=6)
                return
            if not email:
                ui.notification_show("User has no email address.", type="warning")
                return
            user_dict = {"username": username, "email": email}
            svc = NotificationService(config)
            try:
                svc.notify_job_success(
                    user_dict,
                    {
                        "name": "test notification",
                        "duration": None,
                        "working_dir": str(config.user_data_root / username),
                        "stderr": "",
                    },
                )
                ui.notification_show(f"Test email sent to {email}", type="message", duration=4)
            except Exception as e:
                logger.exception("Failed to send test email to user %d", user_id)
                ui.notification_show(f"SMTP error: {e}", type="error", duration=6)

        @reactive.effect
        @reactive.event(input[f"delete_user_{user_id}"])
        def _delete_user():
            m = ui.modal(
                ui.p(
                    "Are you sure you want to permanently delete user ",
                    ui.tags.strong(username),
                    "? This cannot be undone.",
                ),
                title=f"Delete User '{username}'",
                easy_close=True,
                footer=ui.div(
                    ui.input_action_button(
                        f"confirm_delete_{user_id}",
                        "Delete",
                        class_="btn-danger",
                    ),
                    ui.modal_button("Cancel"),
                ),
            )
            ui.modal_show(m)

        @reactive.effect
        @reactive.event(input[f"confirm_delete_{user_id}"])
        def _do_delete_user():
            if not _is_admin():
                ui.notification_show("Administrator access required.", type="error", duration=6)
                return
            try:
                auth_service.delete_user(user_id)
                _audit("delete_user", f"target={username}")
                ui.modal_remove()
                ui.notification_show(f"User '{username}' deleted", type="message", duration=4)
                _refresh()
            except ValueError as exc:
                ui.notification_show(str(exc), type="error", duration=6)
            except Exception as e:
                logger.exception("Failed to delete user %d", user_id)
                ui.notification_show(f"Error: {e}", type="error", duration=6)

    @reactive.effect
    def _register_all_user_actions():
        """Register action handlers for users that don't have them yet.

        Re-runs when users_data changes (e.g. after create), but the
        idempotency guard in _register_user_actions ensures existing users
        never get duplicate handlers.
        """
        users = users_data.get()
        for u in users:
            _register_user_actions(u["id"], u["username"], email=u.get("email"))

    # ------------------------------------------------------------------
    # Create user modal
    # ------------------------------------------------------------------

    @reactive.effect
    @reactive.event(input.create_user_btn)
    def _show_create_modal():
        m = ui.modal(
            ui.input_text("new_username", "Username"),
            ui.input_password("new_password", "Password"),
            ui.input_select("new_role", "Role", choices=sorted(_VALID_ROLES)),
            ui.input_text("new_display_name", "Display Name (optional)"),
            ui.input_text("new_email", "Email (required for user/admin)"),
            ui.output_ui("create_user_errors"),
            title="Create New User",
            easy_close=True,
            footer=ui.div(
                ui.input_action_button("confirm_create_user", "Create", class_="btn-primary"),
                ui.modal_button("Cancel"),
            ),
        )
        ui.modal_show(m)

    @render.ui
    def create_user_errors():
        return ui.div()

    @reactive.effect
    @reactive.event(input.confirm_create_user)
    def _do_create_user():
        if not _is_admin():
            ui.notification_show("Administrator access required.", type="error", duration=6)
            return
        username = input.new_username() or ""
        password = input.new_password() or ""
        role = input.new_role() or "user"
        display_name = input.new_display_name() or None
        email = input.new_email() or None

        errors = _validate_create_user_form(username, password, role, email=email)
        if errors:
            ui.notification_show("; ".join(errors), type="error", duration=5)
            return

        try:
            clean_username = username.strip()
            auth_service.create_user(
                username=clean_username,
                password=password,
                role=role,
                display_name=display_name,
                email=email,
                user_data_root=config.user_data_root,
            )
            _audit("create_user", f"target={clean_username}, role={role}")
            ui.modal_remove()
            home_path = config.user_data_root / clean_username if role != ROLE_TUTORIAL else None
            if home_path:
                ui.notification_show(
                    f"User '{clean_username}' created. Home: {home_path}",
                    type="message",
                    duration=4,
                )
            else:
                ui.notification_show(
                    f"User '{clean_username}' created.",
                    type="message",
                    duration=4,
                )
            _refresh()
        except ValueError as exc:
            ui.notification_show(str(exc), type="error", duration=5)
        except Exception as exc:
            logger.exception("Failed to create user")
            ui.notification_show(f"Error creating user: {exc}", type="error", duration=5)

    # ------------------------------------------------------------------
    # Audit log viewer
    # ------------------------------------------------------------------

    _LOG_PAGE_SIZE = 50
    log_page: reactive.Value[int] = reactive.value(0)
    log_trigger: reactive.Value[int] = reactive.value(0)

    @reactive.effect
    def _populate_log_filters():
        """Populate the user and action filter dropdowns."""
        if not _is_admin() or audit_service is None:
            return
        users = auth_service.list_users()
        user_choices = {"": "All users"}
        user_choices.update({u["username"]: u["username"] for u in users})
        ui.update_select("log_user_filter", choices=user_choices)

        actions = audit_service.distinct_actions()
        action_choices = {"": "All actions"}
        action_choices.update({a: a for a in actions})
        ui.update_select("log_action_filter", choices=action_choices)

    @reactive.effect
    @reactive.event(input.log_refresh_btn)
    def _on_log_refresh():
        log_page.set(0)
        log_trigger.set(log_trigger.get() + 1)

    @reactive.effect
    @reactive.event(input.log_prev_btn)
    def _on_log_prev():
        if log_page.get() > 0:
            log_page.set(log_page.get() - 1)

    @reactive.effect
    @reactive.event(input.log_next_btn)
    def _on_log_next():
        log_page.set(log_page.get() + 1)

    @render.ui
    def log_summary():
        if not _is_admin() or audit_service is None:
            return ui.div()
        _ = log_trigger.get()
        user_filter = input.log_user_filter() or None
        action_filter = input.log_action_filter() or None
        total = audit_service.count(username=user_filter, action=action_filter)
        return ui.div(
            ui.h6("Log Stats"),
            ui.p(f"Total entries: {total}"),
        )

    @render.ui
    def log_page_info():
        if not _is_admin() or audit_service is None:
            return ui.span()
        _ = log_trigger.get()
        page = log_page.get()
        user_filter = input.log_user_filter() or None
        action_filter = input.log_action_filter() or None
        total = audit_service.count(username=user_filter, action=action_filter)
        total_pages = max(1, (total + _LOG_PAGE_SIZE - 1) // _LOG_PAGE_SIZE)
        return ui.span(f"Page {page + 1} of {total_pages}", class_="mx-2 text-muted")

    @render.ui
    def log_table():
        if not _is_admin() or audit_service is None:
            return ui.p("Audit logging is not available.", class_="text-muted")
        _ = log_trigger.get()
        page = log_page.get()
        user_filter = input.log_user_filter() or None
        action_filter = input.log_action_filter() or None

        entries = audit_service.query(
            username=user_filter,
            action=action_filter,
            limit=_LOG_PAGE_SIZE,
            offset=page * _LOG_PAGE_SIZE,
        )
        if not entries:
            return ui.p("No log entries found.", class_="text-muted")

        action_badge_cls = {
            "login": "bg-success",
            "logout": "bg-secondary",
            "login_failed": "bg-danger",
            "create_user": "bg-primary",
            "delete_user": "bg-danger",
            "reset_password": "bg-warning text-dark",
            "change_role": "bg-info text-dark",
        }

        rows = []
        for e in entries:
            badge_cls = action_badge_cls.get(e["action"], "bg-secondary")
            action_html = f'<span class="badge {badge_cls}">{e["action"]}</span>'
            rows.append(
                ui.tags.tr(
                    ui.tags.td(e["timestamp"], style="white-space:nowrap;font-size:0.85em;"),
                    ui.tags.td(e["username"]),
                    ui.tags.td(ui.HTML(action_html)),
                    ui.tags.td(e["detail"], style="font-size:0.85em;"),
                    ui.tags.td(e["ip_address"], style="font-size:0.85em;"),
                )
            )

        return ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(
                    ui.tags.th("Timestamp"),
                    ui.tags.th("User"),
                    ui.tags.th("Action"),
                    ui.tags.th("Detail"),
                    ui.tags.th("IP"),
                )
            ),
            ui.tags.tbody(*rows),
            class_="table table-hover table-sm",
        )
