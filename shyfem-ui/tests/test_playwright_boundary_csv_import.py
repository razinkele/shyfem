"""E2E: a bad boundary CSV cell is reported and the session survives (S-07).

A non-numeric cell raised inside the import effect, and Shiny closes the
session on an exception escaping an effect: the page greyed out and nothing
on it answered any more. The proof the session lives is a later action
still reaching the server.
"""

import re

import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]


def test_bad_csv_cell_notifies_and_the_session_survives(pw_page):
    pw_page.locator(".sf-nav-item[data-nav='Simulation']").click(force=True)
    tab = pw_page.locator("#sf-page-Simulation a.nav-link", has_text="Boundaries").first
    tab.wait_for(state="visible", timeout=15000)
    tab.click()
    expect(tab).to_have_class(re.compile(r"\bactive\b"), timeout=10000)

    # The page is shared across tests, so an earlier one may have left cards.
    cards = pw_page.locator("input[id^='simulation-boundary_editor-bound_nodes_']")
    before = cards.count()

    pw_page.locator("#simulation-boundary_editor-import_csv_btn").click()
    csv = pw_page.locator("#simulation-boundary_editor-csv_input")
    csv.wait_for(state="visible", timeout=10000)
    csv.fill("1 2 3, 1\n4 5, abc")
    pw_page.locator("#simulation-boundary_editor-do_csv_import_btn").click()

    # The server still answers: on main the session was already closed, so
    # this click reached nothing and no card appeared.
    pw_page.wait_for_timeout(1000)
    expect(cards).to_have_count(before)
    pw_page.locator("#simulation-boundary_editor-add_boundary_btn").click()
    expect(cards).to_have_count(before + 1, timeout=10000)
    expect(pw_page.locator("#shiny-disconnected-overlay")).to_have_count(0)

    note = pw_page.locator("#shiny-notification-panel")
    expect(note).to_contain_text("CSV not imported", timeout=10000)
    expect(note).to_contain_text("line 2")
    expect(note).to_contain_text("abc")
