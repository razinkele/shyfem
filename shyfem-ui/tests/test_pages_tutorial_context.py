"""Smoke test: every wizard page server accepts a tutorial_context kwarg.

This guards against page-server signatures drifting back to omitting the
parameter. The Tutorial page's nav-handler relies on every page accepting
this parameter so it can pre-populate the target page's reactive inputs."""
import importlib
import inspect

import pytest


def _unwrap_module_server(fn):
    """Extract the original server function from a @module.server-wrapped callable.

    @module.server does NOT use functools.wraps, so __wrapped__ is absent.
    Instead, the original function is captured as the first cell in the
    closure: wrapper(id, *args, **kwargs) -> fn(input, output, session, *args, **kwargs).
    """
    if fn.__closure__:
        for cell in fn.__closure__:
            try:
                val = cell.cell_contents
            except ValueError:
                continue
            if callable(val) and val is not fn and not isinstance(val, type):
                return val
    return fn


@pytest.mark.parametrize(
    "page", ["compare", "ensemble", "partitioning", "ibm", "files"]
)
def test_page_server_accepts_tutorial_context(page):
    mod = importlib.import_module(f"shyfem_ui.pages.{page}")
    server_fn_name = f"{page}_server"
    server_fn = getattr(mod, server_fn_name, None)
    assert server_fn is not None, f"{server_fn_name} missing in {page}.py"

    # @module.server wraps the original function in a closure; unwrap it to
    # inspect the real parameter list.
    func_to_inspect = _unwrap_module_server(server_fn)
    params = inspect.signature(func_to_inspect).parameters
    assert "tutorial_context" in params, (
        f"{server_fn_name}({tuple(params)}) must accept tutorial_context kwarg"
    )
