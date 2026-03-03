"""Admin panel for user management.

Provides a Shiny module for listing users, creating new users,
resetting passwords, toggling active status, and promoting/demoting roles.
"""

import logging
import re

from shiny import module, reactive, render, ui

from shyfem_ui.config import Config
from shyfem_ui.services.auth_service import AuthService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pure functions (testable without Shiny runtime)
# ---------------------------------------------------------------------------

_VALID_ROLES = {"admin", "user", "tutorial"}


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
        if not re.match(r'^[a-zA-Z0-9._-]{1,64}$', username.strip()):
            errors.append("Username may only contain letters, digits, dots, hyphens, and underscores (1-64 characters)")
    if not password:
        errors.append("Password is required")
    elif len(password) < 4:
        errors.append("Password must be at least 4 characters")
    if role not in _VALID_ROLES:
        errors.append(f"Role must be one of: {', '.join(sorted(_VALID_ROLES))}")
    # Email required for non-tutorial accounts
    if role != "tutorial":
        if not email or not email.strip():
            errors.append("Email is required")
        elif "@" not in email or "." not in email.split("@")[-1]:
            errors.append("Email address is not valid")
    return errors


def _role_badge(role: str) -> str:
    """Return HTML badge for a role."""
    cls = "bg-danger" if role == "admin" else "bg-primary"
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
    return user.get("role") == "admin"


# ---------------------------------------------------------------------------
# Shiny UI module
# ---------------------------------------------------------------------------


@module.ui
def admin_ui():
    """Admin panel UI."""
    return ui.div(
        ui.h3("User Management"),
        ui.hr(),
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
    )


# ---------------------------------------------------------------------------
# Shiny server module
# ---------------------------------------------------------------------------


@module.server
def admin_server(input, output, session, config: Config, auth_service: AuthService):
    """Admin panel server logic."""
    from shyfem_ui.middleware.session_auth import get_current_user

    def _is_admin() -> bool:
        """Check admin access reactively.

        Prefers input.current_user_role() (propagated from JS via Shiny.setInputValue)
        because the Shiny WebSocket context doesn't carry the browser session cookie,
        making get_current_user() always return None behind Shiny Server.
        Falls back to the HTTP-context value as a secondary check.
        """
        try:
            return input.current_user_role() == "admin"
        except Exception:
            return _check_admin_access(get_current_user())

    # Reactive value holding user list (always defined so render functions can reference it)
    users_data: reactive.Value[list[dict]] = reactive.value([])

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
        admins = sum(1 for u in users if u["role"] == "admin")
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
            if u["role"] == "tutorial":
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
                            "Demote" if u["role"] == "admin" else "Promote",
                            class_="btn btn-sm btn-outline-info me-1",
                        ),
                        ui.input_action_link(
                            f"send_test_email_{u['id']}",
                            "Test Email",
                            class_="btn btn-sm btn-outline-primary",
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

    def _register_user_actions(
        user_id: int, username: str, role: str, is_active: bool, email: str | None = None
    ):
        """Register action handlers for a specific user row."""

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
            new_pw = input.reset_pw_value() or ""
            if len(new_pw) < 4:
                ui.notification_show("Password must be at least 4 characters", type="error")
                return
            try:
                auth_service.reset_password(user_id, new_pw)
                ui.modal_remove()
                ui.notification_show(f"Password reset for '{username}'", type="message")
            except Exception as e:
                logger.exception("Failed to reset password for user %d", user_id)
                ui.notification_show(f"Error: {e}", type="error")

        @reactive.effect
        @reactive.event(input[f"toggle_active_{user_id}"])
        def _toggle_active():
            try:
                new_active = not is_active
                auth_service.update_user(user_id, is_active=new_active)
                status = "activated" if new_active else "deactivated"
                ui.notification_show(f"User '{username}' {status}", type="message")
                _refresh()
            except Exception as e:
                logger.exception("Failed to toggle active for user %d", user_id)
                ui.notification_show(f"Error: {e}", type="error")

        @reactive.effect
        @reactive.event(input[f"toggle_role_{user_id}"])
        def _toggle_role():
            try:
                if role == "admin":
                    new_role = "user"
                elif role == "user":
                    new_role = "admin"
                else:  # tutorial or unknown
                    new_role = "user"  # promote tutorial to user first
                auth_service.update_user(user_id, role=new_role)
                action = "demoted to user" if new_role == "user" else "promoted to admin"
                ui.notification_show(f"User '{username}' {action}", type="message")
                _refresh()
            except Exception as e:
                logger.exception("Failed to toggle role for user %d", user_id)
                ui.notification_show(f"Error: {e}", type="error")

        @reactive.effect
        @reactive.event(input[f"send_test_email_{user_id}"])
        def _send_test_email():
            """Send a test notification email to this user."""
            from shyfem_ui.services.notification_service import NotificationService

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
                ui.notification_show(f"Test email sent to {email}", type="message")
            except Exception as e:
                logger.exception("Failed to send test email to user %d", user_id)
                ui.notification_show(f"SMTP error: {e}", type="error")

    @reactive.effect
    def _register_all_user_actions():
        """Re-register action handlers whenever user list changes."""
        users = users_data.get()
        for u in users:
            _register_user_actions(
                u["id"],
                u["username"],
                u["role"],
                u.get("is_active", True),
                email=u.get("email"),
            )

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
            ui.modal_remove()
            home_path = config.user_data_root / clean_username if role != "tutorial" else None
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
