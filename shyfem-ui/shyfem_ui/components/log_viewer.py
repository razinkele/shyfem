"""Log viewer component for displaying command output.

Features:
- Real-time auto-polling with reactive.invalidate_later
- Tail last 500 lines for performance
- Auto-scroll toggle
- Search/filter input
- Separate stdout/stderr tabs
- Download button
"""

import html
from collections.abc import Callable

from shiny import module, reactive, render, ui

MAX_DISPLAY_LINES = 500
LINE_TRUNCATE_LEN = 4096


@module.ui
def log_viewer_ui(
    height: str = "400px",
    show_controls: bool = True,
):
    """Log viewer component UI.

    Args:
        height: CSS height for the log container
        show_controls: Whether to show control buttons
    """
    controls = None
    if show_controls:
        controls = ui.div(
            ui.div(
                ui.input_action_button(
                    "refresh_btn",
                    "Refresh",
                    class_="btn-sm btn-outline-secondary me-2",
                ),
                ui.input_action_button(
                    "clear_btn",
                    "Clear",
                    class_="btn-sm btn-outline-danger me-2",
                ),
                ui.input_action_button(
                    "download_btn",
                    "Download",
                    class_="btn-sm btn-outline-primary me-2",
                ),
                class_="d-flex align-items-center",
            ),
            ui.div(
                ui.input_checkbox(
                    "auto_scroll",
                    "Auto-scroll",
                    value=True,
                ),
                ui.input_checkbox(
                    "auto_poll",
                    "Auto-refresh (2s)",
                    value=False,
                ),
                class_="d-flex align-items-center gap-3",
            ),
            ui.div(
                ui.input_text(
                    "search_filter",
                    None,
                    placeholder="Search / filter lines...",
                    width="100%",
                ),
                class_="mt-1",
            ),
            class_="mb-2",
        )

    return ui.div(
        controls,
        ui.navset_card_pill(
            ui.nav_panel(
                "All",
                ui.div(
                    ui.output_ui("log_content_all"),
                    class_="log-viewer-content",
                    style=f"height: {height}; overflow-y: auto; background-color: #1e1e1e; "
                    f"color: #d4d4d4; font-family: monospace; font-size: 12px; "
                    f"padding: 10px; border-radius: 4px;",
                ),
            ),
            ui.nav_panel(
                "stdout",
                ui.div(
                    ui.output_ui("log_content_stdout"),
                    class_="log-viewer-content",
                    style=f"height: {height}; overflow-y: auto; background-color: #1e1e1e; "
                    f"color: #d4d4d4; font-family: monospace; font-size: 12px; "
                    f"padding: 10px; border-radius: 4px;",
                ),
            ),
            ui.nav_panel(
                "stderr",
                ui.div(
                    ui.output_ui("log_content_stderr"),
                    class_="log-viewer-content",
                    style=f"height: {height}; overflow-y: auto; background-color: #1e1e1e; "
                    f"color: #d4d4d4; font-family: monospace; font-size: 12px; "
                    f"padding: 10px; border-radius: 4px;",
                ),
            ),
        ),
        ui.output_ui("log_stats"),
        class_="log-viewer-component",
    )


@module.server
def log_viewer_server(
    input,
    output,
    session,
    log_content_val: reactive.Value[str],
    on_refresh: Callable[[], None] | None = None,
):
    """Log viewer component server logic.

    Args:
        log_content_val: Reactive value containing log text.
            Supports both plain text and structured format with
            "=== STDOUT ===" / "=== STDERR ===" separators.
        on_refresh: Callback when refresh is clicked
    """
    internal_content = reactive.value("")

    @reactive.effect
    def _sync_content():
        internal_content.set(log_content_val.get())

    # Auto-polling effect
    @reactive.effect
    def _auto_poll_effect():
        try:
            if input.auto_poll():
                reactive.invalidate_later(2)
                if on_refresh:
                    on_refresh()
        except Exception:
            pass

    @reactive.effect
    @reactive.event(input.refresh_btn)
    def _handle_refresh():
        if on_refresh:
            on_refresh()

    @reactive.effect
    @reactive.event(input.clear_btn)
    def _handle_clear():
        internal_content.set("")

    @reactive.effect
    @reactive.event(input.download_btn)
    async def _handle_download():
        content = internal_content.get()
        if not content:
            ui.notification_show("No log content to download", type="warning")
            return
        # Use JS to trigger download via data URI
        import base64
        b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        js = (
            f"var a=document.createElement('a');"
            f"a.href='data:text/plain;base64,{b64}';"
            f"a.download='shyfem_log.txt';"
            f"a.click();"
        )
        await session.send_custom_message("eval_js", js)

    def _split_streams(content: str) -> tuple[str, str]:
        """Split combined log content into stdout and stderr streams."""
        if "=== STDOUT ===" in content and "=== STDERR ===" in content:
            parts = content.split("=== STDERR ===")
            stdout_part = parts[0].replace("=== STDOUT ===", "").strip()
            stderr_part = parts[1].strip() if len(parts) > 1 else ""
            return stdout_part, stderr_part
        return content, ""

    def _filter_and_tail(content: str) -> list[str]:
        """Apply search filter and tail last N lines."""
        if not content:
            return []
        lines = content.splitlines()
        # Tail
        if len(lines) > MAX_DISPLAY_LINES:
            lines = lines[-MAX_DISPLAY_LINES:]
        # Filter
        try:
            search = input.search_filter()
        except Exception:
            search = ""
        if search:
            search_lower = search.lower()
            lines = [line for line in lines if search_lower in line.lower()]
        return lines

    def _render_lines(lines: list[str]) -> ui.Tag:
        """Render log lines as formatted HTML."""
        if not lines:
            return ui.pre(
                "No log output available",
                style="color: #808080; margin: 0;",
            )
        formatted = [format_log_line(line) for line in lines]
        return ui.pre(
            ui.HTML("<br>".join(formatted)),
            style="margin: 0; white-space: pre-wrap; word-wrap: break-word;",
        )

    @render.ui
    def log_content_all():
        content = internal_content.get()
        lines = _filter_and_tail(content)
        return _render_lines(lines)

    @render.ui
    def log_content_stdout():
        content = internal_content.get()
        stdout, _ = _split_streams(content)
        lines = _filter_and_tail(stdout)
        return _render_lines(lines)

    @render.ui
    def log_content_stderr():
        content = internal_content.get()
        _, stderr = _split_streams(content)
        lines = _filter_and_tail(stderr)
        if not lines and not stderr:
            return ui.pre("No stderr output", style="color: #808080; margin: 0;")
        return _render_lines(lines)

    @render.ui
    def log_stats():
        content = internal_content.get()
        if not content:
            return None
        total_lines = len(content.splitlines())
        displayed = min(total_lines, MAX_DISPLAY_LINES)
        stdout, stderr = _split_streams(content)
        stdout_count = len(stdout.splitlines()) if stdout else 0
        stderr_count = len(stderr.splitlines()) if stderr else 0
        parts = [f"Total: {total_lines} lines"]
        if total_lines > MAX_DISPLAY_LINES:
            parts.append(f"(showing last {displayed})")
        if stderr_count > 0:
            parts.append(f"stdout: {stdout_count}")
            parts.append(f"stderr: {stderr_count}")
        return ui.div(
            *[ui.span(s, class_="badge bg-secondary me-1") for s in parts],
            class_="mt-1",
        )

    return internal_content


def format_log_line(line: str) -> str:
    """Apply syntax highlighting to a log line.

    All content is HTML-escaped before any markup is applied to prevent XSS.
    """
    if not isinstance(line, str):
        line = str(line)

    if len(line) > LINE_TRUNCATE_LEN:
        line = line[:LINE_TRUNCATE_LEN] + " [truncated]"

    escaped = html.escape(line, quote=True)

    if "error" in escaped.lower() or "ERROR" in escaped:
        return f'<span style="color: #f44747;">{escaped}</span>'
    elif "warning" in escaped.lower() or "WARNING" in escaped:
        return f'<span style="color: #cca700;">{escaped}</span>'
    elif "success" in escaped.lower() or "completed" in escaped.lower():
        return f'<span style="color: #4ec9b0;">{escaped}</span>'
    elif escaped.startswith("&gt;&gt;&gt;") or escaped.startswith("***"):
        return f'<span style="color: #569cd6;">{escaped}</span>'
    elif "time" in escaped.lower() and "=" in escaped:
        return f'<span style="color: #9cdcfe;">{escaped}</span>'

    return escaped
