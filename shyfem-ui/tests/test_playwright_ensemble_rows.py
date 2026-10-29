"""Ensemble: typed parameter rows survive Add and Remove (R-07).

The row editor re-renders from the stored rows whenever a row is added or
removed. The stored rows only held what a preset or Add put there, so every
value typed into an existing row was wiped by the next Add or Remove.
"""

import pytest
from playwright.sync_api import expect


def _row(page, i: int):
    return (
        page.locator(f"#ensemble-var_section_{i}"),
        page.locator(f"#ensemble-var_param_{i}"),
        page.locator(f"#ensemble-var_values_{i}"),
    )


def _type_row(page, i: int, section: str, param: str, values: str) -> None:
    sec, par, val = _row(page, i)
    sec.fill(section)
    par.fill(param)
    val.fill(values)
    # Shiny debounces text inputs (250 ms); let the values reach the server
    # before the next click, as they would for anyone typing.
    page.wait_for_timeout(600)


def _expect_row(page, i: int, section: str, param: str, values: str) -> None:
    sec, par, val = _row(page, i)
    expect(sec).to_have_value(section, timeout=10000)
    expect(par).to_have_value(param, timeout=10000)
    expect(val).to_have_value(values, timeout=10000)


@pytest.mark.e2e
def test_typed_rows_survive_add_and_remove(pw_page, live_server):
    page = pw_page
    page.locator(".sf-nav-item[data-nav='Ensemble']").click(force=True)
    expect(page.locator("#ensemble-var_param_0")).to_be_visible(timeout=15000)

    _type_row(page, 0, "para", "czdef", "0.02, 0.03")
    page.locator("#ensemble-add_var_btn").click()
    expect(page.locator("#ensemble-var_param_1")).to_be_visible(timeout=10000)
    _expect_row(page, 0, "para", "czdef", "0.02, 0.03")

    _type_row(page, 1, "para", "idt", "10, 30")
    page.locator("#ensemble-add_var_btn").click()
    expect(page.locator("#ensemble-var_param_2")).to_be_visible(timeout=10000)
    _expect_row(page, 0, "para", "czdef", "0.02, 0.03")
    _expect_row(page, 1, "para", "idt", "10, 30")

    _type_row(page, 2, "wind", "ahpar", "1, 5")
    page.locator("#ensemble-remove_var_1").click()
    expect(page.locator("#ensemble-var_param_2")).to_have_count(0, timeout=10000)
    _expect_row(page, 0, "para", "czdef", "0.02, 0.03")
    _expect_row(page, 1, "wind", "ahpar", "1, 5")

    # Leave the page as other tests expect it.
    page.locator("#ensemble-remove_var_1").click()
    expect(page.locator("#ensemble-var_param_1")).to_have_count(0, timeout=10000)
    page.locator(".sf-nav-item[data-nav='Dashboard']").click(force=True)
