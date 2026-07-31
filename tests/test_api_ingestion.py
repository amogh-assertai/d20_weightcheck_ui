"""
POST /api/activities - the full historical record endpoint
(multipart: activity_data JSON string + image file).
"""

import io
import json
import os


def _post(client, activity_data=None, image=True, filename="photo.jpg"):
    data = {}
    if activity_data is not None:
        data["activity_data"] = json.dumps(activity_data)
    if image:
        data["image"] = (io.BytesIO(b"fake-image-bytes"), filename)
    return client.post("/api/activities", data=data, content_type="multipart/form-data")


def test_valid_upload_stores_document_and_image(client, db, today):
    activity = {
        "camera_id": 0,
        "camera_name": "camera_4",
        "activity_number": 42,
        "validation_result": "PASS",
        "timestamp": f"{today.isoformat()}T10:15:00+00:00",
    }
    resp = _post(client, activity)
    assert resp.status_code == 201

    body = resp.get_json()
    assert body["status"] == "stored"
    assert "id" in body

    # Stored in all_activities (NOT the legacy "activities" name)
    doc = db["all_activities"].find_one({"activity_number": 42})
    assert doc is not None
    assert doc["camera_name"] == "camera_4"

    # image_path was injected and the file actually exists on disk
    assert os.path.isfile(doc["image_path"])


def test_image_path_uses_activity_date_not_upload_date(client, db):
    """Folder structure is {date}/{camera_id}__{camera_name}/ using the event's own date."""
    activity = {
        "camera_id": 0,
        "camera_name": "camera_4",
        "activity_number": 7,
        "timestamp": "2026-01-15T10:15:00+00:00",
    }
    _post(client, activity)
    doc = db["all_activities"].find_one({"activity_number": 7})
    assert "2026-01-15" in doc["image_path"]
    assert "0__camera_4" in doc["image_path"]


def test_extra_fields_are_stored_as_is(client, db):
    """Schema is deliberately flexible - unknown fields pass straight through."""
    activity = {
        "camera_id": 1,
        "camera_name": "camera_5",
        "some_future_field": "keep me",
        "nested": {"a": 1},
    }
    _post(client, activity)
    doc = db["all_activities"].find_one({"camera_name": "camera_5"})
    assert doc["some_future_field"] == "keep me"
    assert doc["nested"] == {"a": 1}


def test_missing_image_rejected(client):
    resp = _post(client, {"camera_id": 0, "camera_name": "c"}, image=False)
    assert resp.status_code == 400
    assert "image" in resp.get_json()["error"].lower()


def test_missing_activity_data_rejected(client):
    resp = _post(client, activity_data=None)
    assert resp.status_code == 400


def test_malformed_json_rejected(client):
    resp = client.post(
        "/api/activities",
        data={"activity_data": "not-json", "image": (io.BytesIO(b"x"), "a.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_missing_camera_fields_rejected(client):
    """camera_id/camera_name are required - they build the storage path."""
    resp = _post(client, {"activity_number": 1})
    assert resp.status_code == 400
    assert "camera_id" in resp.get_json()["error"]


def test_camera_id_zero_is_accepted(client, db):
    """Regression guard: camera_id=0 is falsy in Python but perfectly valid."""
    resp = _post(client, {"camera_id": 0, "camera_name": "camera_4", "activity_number": 99})
    assert resp.status_code == 201
