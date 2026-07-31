"""
Live Monitoring page + Settings that drive it, plus the "View Details"
lookup that bridges live data to the full historical record.
"""

import re

import pytest


# =====================================================================
# Card layout & rendering
# =====================================================================

def test_corner_layout_mapping(client):
    """
    Required layout: table 3 top-left, table 1 top-right,
                     table 4 bottom-left, table 2 bottom-right.
    """
    body = client.get("/live-monitoring").data.decode()
    cards = re.findall(
        r'class="table-card (table-card--\w+)[^"]*" data-table-id="(table_\d)"', body
    )
    mapping = {table_id: corner for corner, table_id in cards}
    assert mapping == {
        "table_3": "table-card--tl",
        "table_1": "table-card--tr",
        "table_4": "table-card--bl",
        "table_2": "table-card--br",
    }


def test_empty_cards_show_no_data(client):
    body = client.get("/live-monitoring").data.decode()
    assert body.count("No data yet") == 4


def test_card_field_order(client, db, today):
    """Required order: Activity Number -> RESULT -> Order # -> Datetime."""
    db["live_latest_data"].insert_one({
        "table_id": "table_1", "result": "PASS", "activity_number": 7,
        "activity_datetime": f"{today.isoformat()}T15:30:05+00:00",
        "order_number": "ORD7", "received_at": "2026-07-28T15:30:06+00:00",
    })
    body = client.get("/live-monitoring").data.decode()
    positions = [
        body.index("Activity Number:"),
        body.index("RESULT:"),
        body.index("Order #:"),
        body.index("Datetime:"),
    ]
    assert positions == sorted(positions)


def test_datetime_uses_12_hour_format_with_am_pm(client, db, today):
    db["live_latest_data"].insert_one({
        "table_id": "table_1", "result": "PASS", "activity_number": 1,
        "activity_datetime": f"{today.isoformat()}T14:30:05+00:00",
        "order_number": "ORD1", "received_at": "x",
    })
    body = client.get("/live-monitoring").data.decode()
    assert "02:30:05 PM" in body


def test_page_is_fit_to_screen(client):
    assert "page-fit-screen" in client.get("/live-monitoring").data.decode()


def test_uses_dedicated_stylesheet(client):
    assert "live_monitoring.css" in client.get("/live-monitoring").data.decode()


def test_uses_self_hosted_socketio_not_cdn(client):
    """
    Regression: loading the client from a CDN broke the whole page when the
    CDN was unreachable - the blocking <script> stopped all JS below it.
    """
    body = client.get("/live-monitoring").data.decode()
    assert "/static/js/socket.io.min.js" in body
    assert "cdn.socket.io" not in body


def test_socketio_client_file_is_served(client):
    resp = client.get("/static/js/socket.io.min.js")
    assert resp.status_code == 200
    assert len(resp.data) > 1000


# =====================================================================
# Settings-driven signal behaviour
# =====================================================================

def test_settings_defaults(client):
    body = client.get("/settings").data.decode()
    assert 'value="blink"' in body
    assert 'value="5"' in body


def test_settings_save_and_persist(client, db):
    resp = client.post(
        "/settings",
        data={"pattern": "solid", "duration_sec": "8", "retain_color": "on"},
        follow_redirects=True,
    )
    assert "Settings saved." in resp.data.decode()

    doc = db["app_settings"].find_one({"_id": "live_signal_settings"})
    assert doc["pattern"] == "solid"
    assert doc["duration_sec"] == 8.0
    assert doc["retain_color"] is True


def test_saved_settings_reflected_on_settings_page(client):
    client.post("/settings", data={"pattern": "solid", "duration_sec": "12", "retain_color": "on"})
    body = client.get("/settings").data.decode()
    assert "is-selected" in body
    assert "checked" in body


def _live_config(client):
    """
    The signal/audio config the server hands to live_monitoring.js, parsed
    out of the #live-monitoring-config JSON block.
    """
    import json
    body = client.get("/live-monitoring").data.decode()
    match = re.search(
        r'<script id="live-monitoring-config" type="application/json">\s*(.*?)\s*</script>',
        body, re.DOTALL,
    )
    assert match, "live-monitoring-config block missing from the page"
    return json.loads(match.group(1))


def test_settings_reach_live_monitoring_as_js_config(client):
    client.post("/settings", data={"pattern": "solid", "duration_sec": "8", "retain_color": "on"})
    config = _live_config(client)
    assert config["signal_pattern"] == "solid"
    assert config["signal_duration_ms"] == 8000
    assert config["signal_retain_color"] is True


def test_default_settings_reach_config_block(client):
    config = _live_config(client)
    assert config["signal_pattern"] == "blink"
    assert config["signal_duration_ms"] == 5000
    assert config["signal_retain_color"] is False


@pytest.mark.parametrize("bad_pattern", ["strobe", "", "BLINK", "1"])
def test_invalid_pattern_falls_back_to_blink(client, db, bad_pattern):
    client.post("/settings", data={"pattern": bad_pattern, "duration_sec": "5"})
    assert db["app_settings"].find_one({"_id": "live_signal_settings"})["pattern"] == "blink"


@pytest.mark.parametrize("raw,expected", [("0", 1), ("-5", 1), ("999", 60), ("abc", 5)])
def test_duration_is_clamped_to_sane_bounds(client, db, raw, expected):
    client.post("/settings", data={"pattern": "blink", "duration_sec": raw})
    assert db["app_settings"].find_one({"_id": "live_signal_settings"})["duration_sec"] == expected


def test_retain_color_unchecked_saves_false(client, db):
    client.post("/settings", data={"pattern": "blink", "duration_sec": "5"})
    assert db["app_settings"].find_one({"_id": "live_signal_settings"})["retain_color"] is False


# --- Retained colour must survive a page refresh (server-rendered) ---

def _seed_live(db, today, result="FAIL"):
    db["live_latest_data"].insert_one({
        "table_id": "table_3", "result": result, "activity_number": 12,
        "activity_datetime": f"{today.isoformat()}T10:00:00+00:00",
        "order_number": "ORD12", "received_at": "x",
    })


def _table3_classes(body):
    match = re.search(r'<div class="table-card ([^"]*)" data-table-id="table_3"', body)
    return match.group(1) if match else ""


@pytest.mark.parametrize("pattern", ["blink", "solid"])
def test_retained_colour_shown_after_refresh(client, db, today, pattern):
    """
    Regression: the colour was applied only by JS on a live event, so a
    refresh lost it. It must be rendered server-side from stored data.
    Applies to BOTH patterns, not just blink.
    """
    client.post("/settings", data={"pattern": pattern, "duration_sec": "5", "retain_color": "on"})
    _seed_live(db, today, result="FAIL")

    classes = _table3_classes(client.get("/live-monitoring").data.decode())
    assert "signal--fail" in classes


def test_no_blink_animation_class_on_refresh(client, db, today):
    """The colour persists, but the animation must NOT replay on reload."""
    client.post("/settings", data={"pattern": "blink", "duration_sec": "5", "retain_color": "on"})
    _seed_live(db, today)

    classes = _table3_classes(client.get("/live-monitoring").data.decode())
    assert "signal-blink" not in classes


def test_retain_off_means_no_colour_after_refresh(client, db, today):
    client.post("/settings", data={"pattern": "blink", "duration_sec": "5"})  # retain_color off
    _seed_live(db, today)

    classes = _table3_classes(client.get("/live-monitoring").data.decode())
    assert "signal--fail" not in classes


# =====================================================================
# Audio
# =====================================================================

def test_audio_config_loads_from_json():
    from app.audio_config import load_audio_config
    config = load_audio_config()
    assert "table_1" in config
    for result in ["PASS", "FAIL", "MISSING_DATA"]:
        assert "file" in config["table_1"][result]
        assert "times" in config["table_1"][result]


def _live_monitoring_js():
    """The extracted Live Monitoring script - logic now lives here, not in the template."""
    return open("app/static/js/live_monitoring.js").read()


def test_audio_config_reaches_the_page(client):
    """The mapping is injected as data; the playback logic lives in the JS file."""
    config = _live_config(client)
    assert "table_1" in config["audio_config"]
    assert "playAudioForSignal" in _live_monitoring_js()


def test_audio_only_triggered_from_live_update():
    """
    Audio must fire from the socket-update path only - never on page render.
    Guard: the call sits immediately after applySignal inside updateCard.
    """
    assert re.search(
        r"applySignal\(card, data\.result\);\s*playAudioForSignal\(tableId, data\.result\);",
        _live_monitoring_js(),
    )


def test_missing_audio_files_fail_silently():
    """A 404 on an audio file must not throw or break the repeat chain."""
    js = _live_monitoring_js()
    assert "audioFileMissing" in js
    assert "addEventListener('error'" in js


def test_audio_unlock_ui_present(client):
    body = client.get("/live-monitoring").data.decode()
    assert 'id="audio-status"' in body
    assert 'id="audio-unlock-modal"' in body
    assert "Click anywhere to enable audio" in body


def test_global_unlock_listeners_attached():
    """Any click/tap/key anywhere on the page must unlock audio."""
    js = _live_monitoring_js()
    for event in ["click", "keydown", "touchstart"]:
        assert f"document.addEventListener('{event}', handleUnlockAttempt)" in js


def test_missing_audio_file_returns_404_not_error(client):
    assert client.get("/audio/does_not_exist.mp3").status_code == 404


def test_audio_served_with_long_cache_header(client, app):
    import os
    audio_dir = os.path.join(app.root_path, "static", "audio")
    os.makedirs(audio_dir, exist_ok=True)
    test_file = os.path.join(audio_dir, "_pytest_tmp.mp3")
    with open(test_file, "wb") as f:
        f.write(b"fake-audio")
    try:
        resp = client.get("/audio/_pytest_tmp.mp3")
        assert resp.status_code == 200
        assert "max-age=604800" in resp.headers.get("Cache-Control", "")
    finally:
        os.remove(test_file)


# =====================================================================
# /live-status endpoint
# =====================================================================

def test_live_status_reflects_stored_data(client, db, today):
    _seed_live(db, today, result="PASS")
    data = client.get("/live-status").get_json()
    assert data["table_3"]["result"] == "PASS"
    assert data["table_3"]["order_number"] == "ORD12"
    assert data["table_1"] is None


def test_live_status_includes_formatted_datetime(client, db, today):
    _seed_live(db, today)
    display = client.get("/live-status").get_json()["table_3"]["activity_datetime_display"]
    assert display.endswith("AM") or display.endswith("PM")


# =====================================================================
# View Details lookup (live data -> full historical record)
# =====================================================================

def _lookup_url(activity_number=42, order_number="E0857781", table_id="table_1"):
    return (
        f"/live-monitoring/details?table_id={table_id}"
        f"&activity_number={activity_number}&order_number={order_number}"
    )


def test_lookup_redirects_when_record_exists(client, insert_activity, today):
    activity_id = insert_activity(activity_number=42, order_number="E0857781", date=today)
    resp = client.get(_lookup_url(), follow_redirects=False)
    assert resp.status_code == 302
    assert activity_id in resp.headers["Location"]


def test_lookup_shows_pending_page_when_record_not_uploaded_yet(client):
    """
    The full record arrives via a separate upload path that can lag behind
    the live webhook - so "not found" means "not yet", not an error.
    """
    resp = client.get(_lookup_url())
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Details not ready yet" in body
    assert "Try Now" in body
    assert 'http-equiv="refresh"' in body  # auto-retry after 5s


def test_lookup_ignores_records_from_other_days(client, insert_activity, yesterday):
    """Restricted to today, so a repeated activity_number on another day can't match."""
    insert_activity(activity_number=42, order_number="E0857781", date=yesterday)
    resp = client.get(_lookup_url())
    assert "Details not ready yet" in resp.data.decode()


def test_lookup_matches_on_actual_or_expected_order_number(client, db, today):
    activity_id = str(db["all_activities"].insert_one({
        "camera_id": 0, "camera_name": "camera_4", "activity_number": 42,
        "expected_order_number": "EXPECTED_ONLY", "actual_order_number": None,
        "validation_result": "PASS",
        "timestamp": f"{today.isoformat()}T10:00:00+00:00",
    }).inserted_id)

    resp = client.get(_lookup_url(order_number="EXPECTED_ONLY"), follow_redirects=False)
    assert resp.status_code == 302
    assert activity_id in resp.headers["Location"]


@pytest.mark.parametrize("bad", ["abc", "", "1.5"])
def test_lookup_rejects_bad_activity_number(client, bad):
    resp = client.get(f"/live-monitoring/details?activity_number={bad}&order_number=X")
    assert resp.status_code == 400


def test_lookup_requires_order_number(client):
    assert client.get("/live-monitoring/details?activity_number=1").status_code == 400


@pytest.mark.parametrize("mode,expected", [("new_tab", "_blank"), ("current_tab", "_self")])
def test_details_link_target_follows_config(app, db, mode, expected):
    app.config["LIVE_DETAILS_TYPE"] = mode
    db["live_latest_data"].insert_one({
        "table_id": "table_1", "result": "PASS", "activity_number": 1,
        "activity_datetime": "2026-07-28T10:00:00+00:00",
        "order_number": "ORD1", "received_at": "x",
    })
    body = app.test_client().get("/live-monitoring").data.decode()
    assert f'target="{expected}"' in body
