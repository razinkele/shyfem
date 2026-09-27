"""The app must configure its own logging when it is BUILT, not when a CLI runs.

``logging.basicConfig`` lived inside ``main()``, which only runs for
``python -m shyfem_ui.app``. Shiny Server imports ``app.py`` and calls
``create_app()`` instead, so in production the package was never configured:
Python's last-resort handler passed WARNING and above straight to stderr while
every INFO breadcrumb -- cache reconcile decisions, project opens, build
starts -- was dropped. A smoke test of the live worker log found zero
``shyfem_ui`` lines for a page load that had run several of them.

The request-id filter has a related subtlety. A filter attached to a *logger*
only sees records logged directly to it, never records propagated up from child
loggers, so a handler whose format contains ``%(request_id)s`` raises for every
``shyfem_ui.*`` record unless the filter sits on the HANDLER.
"""

import io
import logging

import pytest

from shyfem_ui.app import configure_cli_logging, configure_logging, create_app
from shyfem_ui.config import Config
from shyfem_ui.middleware.request_id import RequestIdFilter

PACKAGE = "shyfem_ui"


@pytest.fixture(autouse=True)
def restore_logging():
    """Start from a known state, and put the process back as it was.

    Both halves matter. Logging is process-global, so a handler or filter left
    behind by an earlier test leaks into the next one: with only the restore,
    a handler configured by the first test here survived into the third and
    masked a real defect (the request-id test passed in a whole-file run while
    failing when run alone). Clearing first makes each test configure the
    logger itself, which is what it claims to be testing.
    """
    pkg = logging.getLogger(PACKAGE)
    before = (list(pkg.handlers), list(pkg.filters), pkg.level, pkg.propagate)
    pkg.handlers.clear()
    pkg.filters.clear()
    yield
    pkg.handlers[:] = before[0]
    pkg.filters[:] = before[1]
    pkg.setLevel(before[2])
    pkg.propagate = before[3]


def _capture(logger: logging.Logger) -> io.StringIO:
    """Point the configured handler at a buffer instead of stderr."""
    assert logger.handlers, "nothing to capture: the package logger has no handler"
    stream = io.StringIO()
    logger.handlers[0].setStream(stream)
    return stream


def test_building_the_app_configures_package_logging():
    """The regression guard: this is the path Shiny Server takes."""
    create_app(Config(shyfem_dir="/tmp/fake"))

    pkg = logging.getLogger(PACKAGE)
    assert pkg.handlers, "create_app left the package logger unconfigured"
    assert logging.getLogger("shyfem_ui.services.boxmodel_cache").isEnabledFor(logging.INFO)


def test_an_info_record_from_a_child_logger_is_emitted():
    configure_logging(Config(shyfem_dir="/tmp/fake"))
    pkg = logging.getLogger(PACKAGE)
    stream = _capture(pkg)

    logging.getLogger("shyfem_ui.pages.boxmodel").info("cache reconcile: published %s", "run9316")

    out = stream.getvalue()
    assert "cache reconcile: published run9316" in out
    assert "shyfem_ui.pages.boxmodel" in out, "the record must name its logger"
    assert "INFO" in out


def test_the_request_id_filter_sits_on_the_handler():
    """A logger-level filter never sees propagated records, so a child logger's
    record would blow up the ``%(request_id)s`` format. Pinned behaviourally:
    the line must render, with a placeholder when there is no request."""
    configure_logging(Config(shyfem_dir="/tmp/fake"))
    pkg = logging.getLogger(PACKAGE)
    stream = _capture(pkg)

    logging.getLogger("shyfem_ui.services.file_service").warning("quota check")

    out = stream.getvalue()
    assert "quota check" in out
    assert "Logging error" not in out
    assert "-" in out, "request_id should render as a placeholder outside a request"


def test_configuring_twice_does_not_duplicate_handlers():
    """create_app can run more than once in a process (tests, a reload), and a
    second handler would double every line in the worker log."""
    cfg = Config(shyfem_dir="/tmp/fake")
    configure_logging(cfg)
    configure_logging(cfg)

    pkg = logging.getLogger(PACKAGE)
    assert len(pkg.handlers) == 1
    stream = _capture(pkg)
    logging.getLogger("shyfem_ui.x").warning("once")
    assert stream.getvalue().count("once") == 1


def test_the_level_follows_the_config():
    configure_logging(Config(shyfem_dir="/tmp/fake", log_level="WARNING"))
    pkg = logging.getLogger(PACKAGE)
    stream = _capture(pkg)

    logging.getLogger("shyfem_ui.y").info("chatter")
    logging.getLogger("shyfem_ui.y").warning("trouble")

    out = stream.getvalue()
    assert "chatter" not in out
    assert "trouble" in out


def test_package_records_still_propagate_after_the_app_is_built():
    """Propagation must stay ON in the deployed path.

    Under Shiny Server the root has no handler, so a record is emitted exactly
    once either way -- and leaving propagation on is what lets pytest's caplog,
    which is a root handler, see these loggers at all. Turning it off here
    silently blinded ten existing tests, and would silently blind every future
    one, which is a worse failure than a duplicate line in a dev console.
    """
    configure_logging(Config(shyfem_dir="/tmp/fake"))
    assert logging.getLogger(PACKAGE).propagate is True


def test_the_cli_path_stops_propagation_so_lines_are_not_doubled():
    """main() configures the ROOT logger too, for uvicorn. THAT is where a
    shyfem_ui record would be written twice, so the opt-out lives there."""
    root = logging.getLogger()
    before = (list(root.handlers), root.level)
    try:
        configure_cli_logging(Config(shyfem_dir="/tmp/fake"))
        assert logging.getLogger(PACKAGE).propagate is False
        assert root.handlers, "the CLI needs a root handler for uvicorn"
        assert any(
            any(isinstance(f, RequestIdFilter) for f in h.filters) for h in root.handlers
        ), "the root handler needs the request-id filter or the shared format raises"
    finally:
        root.handlers[:] = before[0]
        root.setLevel(before[1])
