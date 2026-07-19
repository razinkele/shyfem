"""N50: prove FK enforcement comes from PRODUCTION code, not the test harness.

tests/conftest.py registers a session-wide ``PRAGMA foreign_keys=ON`` listener
on the SQLAlchemy ``Engine`` *class* (see ``_tests_enforce_sqlite_foreign_keys``)
so that ad-hoc ``create_engine("sqlite:///:memory:")`` fixtures across the suite
mirror production's FK enforcement without each one having to opt in.

That convenience has a blind spot: because the listener is class-wide, it also
fires on the REAL production engine built by ``shyfem_ui.db.base.get_engine()``
— which registers its own equivalent listener at db/base.py:44-53. So a naive
test that just opens a connection through ``get_engine()`` and checks
``PRAGMA foreign_keys`` would keep passing even if that production listener
were deleted entirely, because the conftest-level listener papers over the
gap. tests/test_db_fk.py's docstring claims to "pin that enforcement is active
on the production engine" but cannot actually detect that regression.

This test closes the gap: it uses ``fk_listener_detached()`` (conftest.py) to
remove the blanket test listener for the duration of the assertion, so any FK
enforcement observed on a ``base.get_engine()`` connection can only have come
from production's own connect-listener.

Verified manually: with the ``cur.execute("PRAGMA foreign_keys=ON")`` line in
``shyfem_ui/db/base.py::get_engine`` commented out, this test fails (assert
1 == 0); tests/test_db_fk.py's own tests still pass unchanged because they
never detach the harness-wide listener. Restoring the line makes this test
pass again.
"""

from tests.conftest import fk_listener_detached


def test_production_engine_enforces_fk_without_test_harness_listener(tmp_path, monkeypatch):
    """base.get_engine() must itself set PRAGMA foreign_keys=ON.

    RED premise: before this test existed, nothing distinguished "FKs are
    enforced because production registered its own listener" from "FKs are
    enforced because conftest's class-wide listener happens to also apply
    here" -- test_db_fk.py would keep passing either way. This test removes
    that ambiguity by detaching the conftest listener before building the
    engine.
    """
    import shyfem_ui.config as cfg
    import shyfem_ui.db.base as base

    db = tmp_path / "prod_listener.db"
    monkeypatch.setattr(cfg, "_config", cfg.Config(database_url=f"sqlite:///{db}"))
    monkeypatch.setattr(base, "_engine", None)
    monkeypatch.setattr(base, "_SessionLocal", None)

    engine = None
    with fk_listener_detached():
        engine = base.get_engine()
        with engine.connect() as conn:
            enforced = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()

    engine.dispose()

    assert enforced == 1, (
        "shyfem_ui.db.base.get_engine() did not enforce PRAGMA foreign_keys=ON "
        "on its own connect-listener -- with the test-harness-wide FK "
        "listener detached, the production engine factory must be "
        "self-sufficient (N50: the guarantee must come from production "
        "code, not from tests/conftest.py's convenience listener)."
    )
