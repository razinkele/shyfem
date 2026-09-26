"""Test helpers for the Section M file-picker rollout."""

import inspect


def get_server_source(page_module, server_name: str) -> str:
    """Unwrap the @module.server decorator and return the inner source.

    @module.server wraps the decorated function in a closure that
    handles namespace scoping. inspect.getsource on the wrapped name
    returns the wrapper body, which doesn't contain the page server's
    actual code. Unwrap via __closure__[0].cell_contents to reach the
    inner function before calling getsource.

    Used by per-page wiring assertion tests to verify the project_select dropdown
    calls + file_types filters + reactive.isolate guards inside the page
    server body.
    """
    fn = getattr(page_module, server_name)
    inner = fn.__closure__[0].cell_contents
    assert inner.__name__ == server_name, (
        f"closure[0] is {inner.__name__!r}, expected {server_name!r}"
    )
    return inspect.getsource(inner)
