"""
Cross-cutting infrastructure: error pages, shared helpers, theming,
and the multi-worker consistency guarantee.
"""

import pytest

from app.utils.helpers import (
    format_timestamp,
    format_timestamp_12h,
    is_allowed_file,
    utc_now_iso,
)


# =====================================================================
# Error pages
# =====================================================================

def test_custom_404_page(client):
    resp = client.get("/no-such-route")
    assert resp.status_code == 404
    body = resp.data.decode()
    assert "Page not found" in body
    assert "Refresh" in body


def test_custom_500_page(db):
    """
    The custom 500 page only renders when DEBUG=False (with debug on, Flask's
    interactive debugger takes over instead - intentional, so devs keep
    tracebacks).

    PROPAGATE_EXCEPTIONS must be forced off here: Flask re-raises exceptions
    to the caller when TESTING=True, which would bypass the error handler
    entirely and tell us nothing about what a real user would see.
    """
    from tests.conftest import TestConfig
    from app import create_app

    class BoomConfig(TestConfig):
        PROPAGATE_EXCEPTIONS = False

    application = create_app(BoomConfig)
    application.extensions["mongo_db"] = db

    @application.route("/_boom")
    def _boom():
        raise RuntimeError("simulated crash")

    resp = application.test_client().get("/_boom")
    assert resp.status_code == 500
    body = resp.data.decode()
    assert "Something went wrong" in body
    assert "Refresh" in body


def test_error_pages_keep_site_branding(client):
    body = client.get("/no-such-route").data.decode()
    assert "Watts-Water-D20" in body


# =====================================================================
# Shared helpers
# =====================================================================

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-07-24T22:28:48+00:00", "24 Jul 2026, 22:28:48"),
        ("2026-07-24T22:28:48Z", "24 Jul 2026, 22:28:48"),
        ("2026-01-05T09:05:00+00:00", "05 Jan 2026, 09:05:00"),
    ],
)
def test_format_timestamp_24h(raw, expected):
    assert format_timestamp(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-07-28T14:30:05+00:00", "28 Jul 2026, 02:30:05 PM"),
        ("2026-07-28T09:05:00+00:00", "28 Jul 2026, 09:05:00 AM"),
        ("2026-07-28T00:00:00+00:00", "28 Jul 2026, 12:00:00 AM"),
        ("2026-07-28T12:00:00+00:00", "28 Jul 2026, 12:00:00 PM"),
    ],
)
def test_format_timestamp_12h(raw, expected):
    assert format_timestamp_12h(raw) == expected


@pytest.mark.parametrize("formatter", [format_timestamp, format_timestamp_12h])
def test_formatters_handle_empty_and_garbage(formatter):
    assert formatter(None) == "-"
    assert formatter("") == "-"
    assert formatter("not-a-date") == "not-a-date"  # passed through, not crashed


def test_is_allowed_file():
    assert is_allowed_file("photo.jpg", {"jpg", "png"}) is True
    assert is_allowed_file("photo.JPG", {"jpg", "png"}) is True  # case-insensitive
    assert is_allowed_file("photo.gif", {"jpg", "png"}) is False
    assert is_allowed_file("noextension", {"jpg"}) is False
    assert is_allowed_file("", {"jpg"}) is False


def test_utc_now_iso_is_parseable_utc():
    from datetime import datetime
    parsed = datetime.fromisoformat(utc_now_iso())
    assert parsed.tzinfo is not None


# =====================================================================
# Theme
# =====================================================================

def test_theme_applied_before_paint_to_avoid_flash(client):
    """The saved theme is read in <head> so there's no wrong-theme flicker."""
    body = client.get("/").data.decode()
    head = body.split("</head>")[0]
    assert "localStorage.getItem('theme')" in head


def test_theme_toggle_script_loaded(client):
    assert "js/main.js" in client.get("/").data.decode()


# =====================================================================
# Multi-worker consistency
# =====================================================================

def test_live_status_reads_are_shared_across_app_instances(db, today):
    """
    Regression: live status was cached in-process, so with multiple Gunicorn
    workers a webhook handled by one worker was invisible to another - data
    appeared to randomly revert. Reads must come from MongoDB every time.

    Two separate app instances here stand in for two separate workers.
    """
    from tests.conftest import TestConfig
    from app import create_app

    worker_a = create_app(TestConfig)
    worker_a.extensions["mongo_db"] = db
    worker_b = create_app(TestConfig)
    worker_b.extensions["mongo_db"] = db

    payload = {
        "table_id": "table_1", "result": "PASS", "activity_number": 1,
        "activity_datetime": f"{today.isoformat()}T09:00:00+00:00",
        "order_number": "ORDER_FIRST",
    }
    worker_a.test_client().post("/api/webhook/activity-result", json=payload)

    # Worker B must immediately see what worker A wrote
    seen_by_b = worker_b.test_client().get("/live-status").get_json()
    assert seen_by_b["table_1"]["order_number"] == "ORDER_FIRST"

    # And an update via A must not "revert" when read from B
    payload.update({"activity_number": 2, "order_number": "ORDER_SECOND"})
    worker_a.test_client().post("/api/webhook/activity-result", json=payload)

    seen_by_b = worker_b.test_client().get("/live-status").get_json()
    assert seen_by_b["table_1"]["order_number"] == "ORDER_SECOND"


# =====================================================================
# Collection naming
# =====================================================================

def test_three_collections_are_used_as_documented(client, db, today, webhook_payload, insert_activity):
    """all_activities (history), live_latest_data (live), app_settings (config)."""
    insert_activity(date=today)
    client.post("/api/webhook/activity-result", json=webhook_payload())
    client.post("/settings", data={"pattern": "solid", "duration_sec": "5"})

    names = set(db.list_collection_names())
    assert {"all_activities", "live_latest_data", "app_settings"} <= names
