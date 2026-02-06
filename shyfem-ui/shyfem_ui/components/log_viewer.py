"""Log viewer component for displaying command output."""

from typing import Callable, Optional

from shiny import module, reactive, render, ui


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
            ui.input_checkbox(
                "auto_scroll",
                "Auto-scroll",
                value=True,
            ),
            class_="d-flex align-items-center mb-2",
        )

    return ui.div(
        controls,
        ui.div(
            ui.output_ui("log_content"),
            class_="log-viewer-content",
            style=f"height: {height}; overflow-y: auto; background-color: #1e1e1e; "
            f"color: #d4d4d4; font-family: monospace; font-size: 12px; "
            f"padding: 10px; border-radius: 4px;",
        ),
        class_="log-viewer-component",
    )


@module.server
def log_viewer_server(
    input,
    output,
    session,
    log_content_val: reactive.Value[str],
    on_refresh: Optional[Callable[[], None]] = None,
):
    """Log viewer component server logic.

    Args:
        log_content_val: Reactive value containing log text
        on_refresh: Callback when refresh is clicked
    """
    internal_content = reactive.value("")

    @reactive.effect
    def _sync_content():
        internal_content.set(log_content_val.get())

    @reactive.effect
    @reactive.event(input.refresh_btn)
    def _handle_refresh():
        if on_refresh:
            on_refresh()

    @reactive.effect
    @reactive.event(input.clear_btn)
    def _handle_clear():
        internal_content.set("")

    @render.ui
    def log_content():
        content = internal_content.get()
        if not content:
            return ui.pre(
                "No log output available",
                style="color: #808080; margin: 0;",
            )

        # Apply syntax highlighting for common patterns
        lines = content.split("\n")
        formatted_lines = []

        for line in lines:
            formatted = format_log_line(line)
            formatted_lines.append(formatted)

        return ui.pre(
            ui.HTML("<br>".join(formatted_lines)),
            style="margin: 0; white-space: pre-wrap; word-wrap: break-word;",
        )

    return internal_content


def format_log_line(line: str) -> str:
    """Apply syntax highlighting to a log line."""
    import html

    # Escape HTML first
    escaped = html.escape(line)

    # Apply colors for common patterns
    if "error" in escaped.lower() or "ERROR" in escaped:
        return f'<span style="color: #f44747;">{escaped}</span>'
    elif "warning" in escaped.lower() or "WARNING" in escaped:
        return f'<span style="color: #cca700;">{escaped}</span>'
    elif "success" in escaped.lower() or "completed" in escaped.lower():
        return f'<span style="color: #4ec9b0;">{escaped}</span>'
    elif escaped.startswith(">>>") or escaped.startswith("***"):
        return f'<span style="color: #569cd6;">{escaped}</span>'
    elif "time" in escaped.lower() and "=" in escaped:
        return f'<span style="color: #9cdcfe;">{escaped}</span>'

    return escaped
