"""
Static-asset wiring.

Guards the CSS/JS split: a page missing its stylesheet would still return
200 and pass every other test, while being visually broken. These assert
the actual <link>/<script> tags are present and that each file is served.
"""

import glob
import os
import re

import pytest

# Every page gets base.css + forms.css from base.html; extras are per-page.
PAGE_STYLESHEETS = {
    "/": [],
    "/live-monitoring": ["live_monitoring.css"],
    "/settings": [],
    "/history": ["history.css"],
    "/analytics/system": ["analytics.css"],
    "/analytics/accuracy": ["analytics.css"],
}

ALL_STYLESHEETS = [
    "base.css", "forms.css", "history.css",
    "activity_detail.css", "analytics.css", "errors.css", "live_monitoring.css",
]


@pytest.mark.parametrize("route", list(PAGE_STYLESHEETS))
def test_shared_stylesheets_on_every_page(client, route):
    body = client.get(route).data.decode()
    assert "css/base.css" in body
    assert "css/forms.css" in body


@pytest.mark.parametrize("route,extras", PAGE_STYLESHEETS.items())
def test_page_specific_stylesheets(client, route, extras):
    body = client.get(route).data.decode()
    for sheet in extras:
        assert f"css/{sheet}" in body, f"{route} is missing {sheet}"


def test_activity_detail_loads_its_stylesheet(client, insert_activity, today):
    activity_id = insert_activity(date=today)
    body = client.get(f"/history/activity/{activity_id}").data.decode()
    assert "css/activity_detail.css" in body


def test_error_pages_load_error_stylesheet(client):
    assert "css/errors.css" in client.get("/no-such-route").data.decode()


@pytest.mark.parametrize("sheet", ALL_STYLESHEETS)
def test_every_stylesheet_is_served(client, sheet):
    resp = client.get(f"/static/css/{sheet}")
    assert resp.status_code == 200
    assert len(resp.data) > 0


def test_no_page_references_the_removed_monolithic_stylesheet(client, insert_activity, today):
    """style.css was split into 6 files - nothing should still point at it."""
    activity_id = insert_activity(date=today)
    routes = list(PAGE_STYLESHEETS) + [f"/history/activity/{activity_id}", "/no-such-route"]
    for route in routes:
        assert "css/style.css" not in client.get(route).data.decode(), route


# --- JavaScript ---

def test_shared_script_on_every_page(client):
    for route in PAGE_STYLESHEETS:
        assert "js/main.js" in client.get(route).data.decode()


def test_page_scripts_are_served(client):
    for script in ["main.js", "socket.io.min.js", "live_monitoring.js", "activity_detail.js"]:
        resp = client.get(f"/static/js/{script}")
        assert resp.status_code == 200, f"{script} not served"


def test_live_monitoring_uses_external_script_not_inline(client):
    """
    The 210-line inline block was extracted so the browser can cache it.
    Config still comes from the server, but the logic must be external.
    """
    body = client.get("/live-monitoring").data.decode()
    assert "js/live_monitoring.js" in body


def test_activity_detail_uses_external_script_not_inline(client, insert_activity, today):
    activity_id = insert_activity(date=today)
    body = client.get(f"/history/activity/{activity_id}").data.decode()
    assert "js/activity_detail.js" in body


def test_templates_contain_no_large_inline_scripts():
    """
    Regression guard against inline JS creeping back in. The small
    theme-before-paint snippet in base.html is deliberately inline (it must
    run before first paint to avoid a flash of the wrong theme).
    """
    allowed_inline = {"base.html"}
    for path in glob.glob("app/templates/**/*.html", recursive=True):
        if os.path.basename(path) in allowed_inline:
            continue
        content = open(path).read()
        for block in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", content, re.DOTALL):
            # JSON config blocks are data, not logic - those are fine.
            if 'type="application/json"' in content and block.strip().startswith("{"):
                continue
            line_count = len([l for l in block.split("\n") if l.strip()])
            assert line_count <= 10, (
                f"{path} has a {line_count}-line inline script - extract it to static/js/"
            )
