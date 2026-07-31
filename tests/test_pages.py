"""
Smoke tests: every page route renders without error, and shared chrome
(nav, branding, theme toggle) is present.
"""

import pytest

ALL_PAGE_ROUTES = [
    "/",
    "/live-monitoring",
    "/settings",
    "/history",
    "/analytics/system",
    "/analytics/accuracy",
]


@pytest.mark.parametrize("route", ALL_PAGE_ROUTES)
def test_page_renders(client, route):
    assert client.get(route).status_code == 200


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.data == b"OK"


def test_analytics_root_redirects_to_system(client):
    resp = client.get("/analytics", follow_redirects=False)
    assert resp.status_code == 302
    assert "/analytics/system" in resp.headers["Location"]


@pytest.mark.parametrize("route", ALL_PAGE_ROUTES)
def test_nav_and_branding_present(client, route):
    """Every page shares the top bar: client name, nav links, theme toggle."""
    body = client.get(route).data.decode()
    assert "Watts-Water-D20" in body
    assert 'class="navbar"' in body
    assert 'id="theme-toggle"' in body
    for label in ["Home", "Live Monitoring", "Settings", "History", "Analytics"]:
        assert label in body


def test_default_theme_is_dark(client):
    assert 'data-theme="dark"' in client.get("/").data.decode()


def test_live_status_endpoint_returns_all_four_tables(client):
    data = client.get("/live-status").get_json()
    assert set(data.keys()) == {"table_1", "table_2", "table_3", "table_4"}
