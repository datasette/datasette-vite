"""Playwright browser tests verifying real Vite builds execute correctly.

This file is named to sort after test_vite.py so that Playwright's event loop
does not interfere with pytest-asyncio tests.

Skip all browser tests with: pytest -m "not browser"
"""

import pytest

pytestmark = pytest.mark.browser


def test_vanilla_ts_browser(page, fixture_server):
    """Vanilla TS: JS sets document.title and CSS applies background color."""
    url = fixture_server("vanilla-ts", "src/main.ts")

    page.goto(url)
    page.wait_for_function("document.title === 'vanilla-loaded'")

    bg = page.evaluate("window.getComputedStyle(document.body).backgroundColor")
    assert bg == "rgb(30, 30, 30)"


def test_svelte_ts_browser(page, fixture_server):
    """Svelte TS: component renders with correct text and styled background."""
    url = fixture_server("svelte-ts", "src/main.ts", extra_body='<div id="app"></div>')

    page.goto(url)
    page.wait_for_selector("#svelte-root")

    assert page.text_content("#svelte-root") == "svelte-loaded"

    bg = page.evaluate(
        "window.getComputedStyle(document.querySelector('#svelte-root')).backgroundColor"
    )
    assert bg == "rgb(30, 30, 30)"


def test_react_ts_browser(page, fixture_server):
    """React TS: component renders with correct text and styled background."""
    url = fixture_server("react-ts", "src/main.tsx", extra_body='<div id="app"></div>')

    page.goto(url)
    page.wait_for_selector("#react-root")

    assert page.text_content("#react-root") == "react-loaded"

    bg = page.evaluate(
        "window.getComputedStyle(document.querySelector('#react-root')).backgroundColor"
    )
    assert bg == "rgb(30, 30, 30)"
