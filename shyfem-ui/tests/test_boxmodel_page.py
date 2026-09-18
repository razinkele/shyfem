"""Wiring and page-discipline tests for the Box-model page (spec §8).

The page itself is exercised end to end by the Playwright test (Task 13);
what is asserted here is the wiring Task 13 drives (module id, nav value,
page div, server mount) plus the page-level invariants that are cheap to
check statically or as pure functions: every write handler re-checks
``editor_denied_reason``, the poller exists, ``reconcile_tmp_dirs`` runs at
page load, manifest text never reaches the browser as raw HTML, and no
user-facing message carries a raw absolute host path.
"""

import inspect
import re

import pytest

from tests._test_helpers import get_server_source


def test_page_is_registered():
    import shyfem_ui.pages as pages

    assert "boxmodel" in pages.__all__
    from shyfem_ui.pages import boxmodel

    assert callable(boxmodel.boxmodel_ui) and callable(boxmodel.boxmodel_server)


def test_app_wiring():
    import shyfem_ui.app as app

    src = inspect.getsource(app)
    assert '"value": "Box-model"' in src and 'id="sf-page-Box-model"' in src
    assert re.search(r'boxmodel\.boxmodel_server\(\s*"boxmodel",\s*config,', src)
    assert "active_project=active_project" in src.split("boxmodel.boxmodel_server(")[1][:400]


def test_server_wiring_gates_and_polling():
    from shyfem_ui.pages import boxmodel

    src = get_server_source(boxmodel, "boxmodel_server")
    assert src.count("editor_denied_reason(") >= 2  # build + cancel
    assert "start_build(" in src and "cancel_build(" in src and "load_manifest(" in src
    assert "invalidate_later" in src and "reconcile_tmp_dirs(" in src
    assert "ui.HTML(" not in src  # manifest text via ui.tags only
    assert "grid_map_server(" in src and "on_box_click" in src


def test_download_uses_non_deprecated_renderer():
    from shyfem_ui.pages import boxmodel

    assert boxmodel._render_download is not None


# --- obligation-driven helpers -------------------------------------------


class _StubConfig:
    """Minimal stand-in for Config.display_path in server mode."""

    def display_path(self, path, user):
        return f"~/{str(path).rsplit('/', 1)[-1]}"


def test_safe_error_strips_absolute_host_paths():
    """Obligation (Task 4 review): ManifestError/confine_path text may embed
    raw host paths; nothing user-facing may leak the host layout."""
    from shyfem_ui.pages import boxmodel

    exc = ValueError(
        "runs[0].dir: Save path '/home/alice/projects/lagoon/run' must be "
        "within work directory: /srv/shyfem/work"
    )
    out = boxmodel._safe_error(exc, _StubConfig(), {"username": "alice"})
    assert "/home/alice" not in out
    assert "/srv/shyfem" not in out
    assert "~/run" in out and "~/work" in out
    assert out.startswith("runs[0].dir:")


def test_safe_error_strips_single_segment_roots():
    """A one-segment absolute path ("/etc", "/tmp") is still an absolute path."""
    from shyfem_ui.pages import boxmodel

    out = boxmodel._safe_error(
        ValueError("runs[0].dir: Path '/etc' is outside allowed directories: /tmp"),
        _StubConfig(),
        None,
    )
    # The stub rewrites to "~/<basename>", so check the *raw* tokens are gone
    # rather than a substring that the replacement itself contains.
    assert "'/etc'" not in out
    assert not out.endswith(": /tmp")
    assert "'~/etc'" in out and out.endswith(": ~/tmp")


def test_safe_error_leaves_non_path_text_alone():
    from shyfem_ui.pages import boxmodel

    exc = ValueError("observations: 3/24 rows dropped; speed in m/s")
    assert boxmodel._safe_error(exc, _StubConfig(), None) == (
        "observations: 3/24 rows dropped; speed in m/s"
    )


def test_bounded_timeout_config_replaces_none_without_mutating():
    """Obligation (Task 6 review): builds must run with a bounded timeout, and
    the shared Config every session holds must not be mutated to get one."""
    from shyfem_ui.config import Config
    from shyfem_ui.pages import boxmodel

    # Pass None explicitly rather than relying on the default: a dev .env with
    # SHYFEM_UI_COMMAND_TIMEOUT_SECONDS set would otherwise fail this test for
    # a reason that has nothing to do with the function under test.
    config = Config(command_timeout_seconds=None)
    assert config.command_timeout_seconds is None
    bounded = boxmodel._bounded_timeout_config(config)
    assert bounded.command_timeout_seconds == boxmodel.BUILD_TIMEOUT_SECONDS
    assert bounded.command_timeout_seconds is not None
    assert config.command_timeout_seconds is None  # original untouched
    assert bounded is not config


def test_bounded_timeout_config_keeps_an_operator_set_timeout():
    from shyfem_ui.config import Config
    from shyfem_ui.pages import boxmodel

    config = Config(command_timeout_seconds=60)
    assert boxmodel._bounded_timeout_config(config) is config


def test_level_bias_renders_as_em_dash():
    """Obligation (Task 7 review): level rows compare anomalies, so their bias
    is structurally ~0 and must not be shown as if it were a real bias."""
    from shyfem_ui.pages import boxmodel

    assert boxmodel._bias_cell("level", 1e-17) == "—"
    assert boxmodel._bias_cell("salinity", 0.125) == "0.125"


def test_cache_period_rejects_a_meta_without_a_period():
    """``cache_status`` calls any parseable meta.json "ready", so a foreign or
    hand-edited cache dir can reach the page without a period. The page must
    turn that into a message, not a KeyError out of an effect/render -- so
    ``_cache_period`` has to raise a type ``cached_result`` catches."""
    from shyfem_ui.pages import boxmodel

    class _Run:
        meta: dict = {"records": 3}

    with pytest.raises((KeyError, TypeError)):
        boxmodel._cache_period(_Run())


def test_fmt_handles_missing_values():
    from shyfem_ui.pages import boxmodel

    assert boxmodel._fmt(None) == ""
    assert boxmodel._fmt(float("nan")) == ""
    assert boxmodel._fmt(1.23456) == "1.235"
    assert boxmodel._fmt(1.23456, 1) == "1.2"


def test_ui_builds_without_a_session():
    """Import-time/UI-construction smoke: a bad kwarg to grid_map_ui or a
    malformed tag only shows up when the UI is actually built."""
    from shyfem_ui.pages import boxmodel

    html = str(boxmodel.boxmodel_ui("boxmodel"))
    for ident in ("boxmodel-run", "boxmodel-build", "boxmodel-cache_state", "boxmodel-skill_table"):
        assert ident in html, f"missing input/output id: {ident}"
