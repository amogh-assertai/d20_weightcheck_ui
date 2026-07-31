"""
POST /api/webhook/activity-result - the lightweight live-signal webhook.

Covers the two behaviours that caused real bugs in the past:
  1. Duplicate suppression (a looping sender must not re-trigger signals).
  2. Broadcast to browsers AND persistence to MongoDB both happening.
"""

import pytest

REQUIRED = ["result", "activity_number", "activity_datetime", "order_number"]


def test_valid_webhook_accepted_and_persisted(client, db, webhook_payload):
    resp = client.post("/api/webhook/activity-result", json=webhook_payload())
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "recorded"

    doc = db["live_latest_data"].find_one({"table_id": "table_1"})
    assert doc["result"] == "PASS"
    assert doc["activity_number"] == 1
    assert doc["received_at"]


def test_webhook_does_not_touch_all_activities(client, db, webhook_payload):
    """This endpoint is live-display only - history comes from /api/activities."""
    client.post("/api/webhook/activity-result", json=webhook_payload())
    assert db["all_activities"].count_documents({}) == 0


def test_repeated_identical_webhook_is_ignored(client, db, webhook_payload):
    """
    Regression: a sender looping on the same activity used to re-trigger the
    blink/audio endlessly, because received_at was rewritten every time.
    """
    payload = webhook_payload()
    client.post("/api/webhook/activity-result", json=payload)
    first_received_at = db["live_latest_data"].find_one({"table_id": "table_1"})["received_at"]

    for _ in range(15):
        resp = client.post("/api/webhook/activity-result", json=payload)
        assert resp.get_json()["status"] == "duplicate_ignored"

    doc = db["live_latest_data"].find_one({"table_id": "table_1"})
    assert doc["received_at"] == first_received_at, "received_at must not change on duplicates"
    assert db["live_latest_data"].count_documents({"table_id": "table_1"}) == 1


def test_new_activity_number_is_not_a_duplicate(client, db, webhook_payload):
    client.post("/api/webhook/activity-result", json=webhook_payload(activity_number=1))
    resp = client.post("/api/webhook/activity-result", json=webhook_payload(activity_number=2))
    assert resp.get_json()["status"] == "recorded"
    assert db["live_latest_data"].find_one({"table_id": "table_1"})["activity_number"] == 2


def test_changed_result_same_activity_is_not_a_duplicate(client, webhook_payload):
    """A late correction on the same activity should still come through."""
    client.post("/api/webhook/activity-result", json=webhook_payload(result="PASS"))
    resp = client.post("/api/webhook/activity-result", json=webhook_payload(result="FAIL"))
    assert resp.get_json()["status"] == "recorded"


def test_upsert_keeps_exactly_one_document_per_table(client, db, webhook_payload):
    for n in range(1, 6):
        client.post("/api/webhook/activity-result", json=webhook_payload(activity_number=n))
    assert db["live_latest_data"].count_documents({"table_id": "table_1"}) == 1


def test_tables_are_independent(client, db, webhook_payload):
    client.post("/api/webhook/activity-result", json=webhook_payload(table_id="table_1", order_number="A"))
    client.post("/api/webhook/activity-result", json=webhook_payload(table_id="table_3", order_number="B"))
    assert db["live_latest_data"].find_one({"table_id": "table_1"})["order_number"] == "A"
    assert db["live_latest_data"].find_one({"table_id": "table_3"})["order_number"] == "B"
    assert db["live_latest_data"].find_one({"table_id": "table_2"}) is None


# --- Validation ---

def test_non_json_body_rejected(client):
    resp = client.post("/api/webhook/activity-result", data="not json")
    assert resp.status_code == 400


@pytest.mark.parametrize("bad_table", ["table_9", "table_0", "", "TABLE_1", None])
def test_invalid_table_id_rejected(client, webhook_payload, bad_table):
    payload = webhook_payload()
    payload["table_id"] = bad_table
    resp = client.post("/api/webhook/activity-result", json=payload)
    assert resp.status_code == 400
    assert "table_id" in resp.get_json()["error"]


@pytest.mark.parametrize("missing_field", REQUIRED)
def test_each_required_field_is_enforced(client, webhook_payload, missing_field):
    payload = webhook_payload()
    del payload[missing_field]
    resp = client.post("/api/webhook/activity-result", json=payload)
    assert resp.status_code == 400
    assert missing_field in resp.get_json()["error"]


# --- WebSocket broadcast ---

def test_new_data_is_broadcast_to_connected_clients(client, socket_client, webhook_payload):
    assert socket_client.is_connected()
    socket_client.get_received()  # drain anything from connect

    client.post("/api/webhook/activity-result", json=webhook_payload(table_id="table_2", result="FAIL"))

    events = [e for e in socket_client.get_received() if e["name"] == "table_update"]
    assert len(events) == 1
    payload = events[0]["args"][0]
    assert payload["table_id"] == "table_2"
    assert payload["result"] == "FAIL"
    assert payload["activity_datetime_display"]  # formatted for display


def test_duplicate_does_not_broadcast(client, socket_client, webhook_payload):
    payload = webhook_payload()
    client.post("/api/webhook/activity-result", json=payload)
    socket_client.get_received()  # drain the first (legitimate) broadcast

    client.post("/api/webhook/activity-result", json=payload)
    events = [e for e in socket_client.get_received() if e["name"] == "table_update"]
    assert events == [], "a duplicate must not reach browser clients"


def test_broadcast_datetime_uses_12_hour_format(client, socket_client, webhook_payload):
    socket_client.get_received()
    client.post("/api/webhook/activity-result", json=webhook_payload(hour=14))
    events = [e for e in socket_client.get_received() if e["name"] == "table_update"]
    display = events[0]["args"][0]["activity_datetime_display"]
    assert display.endswith("AM") or display.endswith("PM")
