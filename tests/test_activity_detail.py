"""
Activity Details page: rendering, image serving, prev/next navigation within
the filtered set, and the review form's result_reviewed logic.
"""

import os
import re

import pytest


def test_detail_page_renders_all_fields(client, insert_activity, today):
    activity_id = insert_activity(
        activity_number=42,
        order_number="E0857781",
        date=today,
        validation_result="FAIL",
        expected_weight="90.273",
        actual_weight="91.6",
        weight_difference="1.327",
        weight_difference_percent="1.47%",
        order_number_reason="Order number matched",
        weight_reason="Exceeded tolerance",
    )
    body = client.get(f"/history/activity/{activity_id}").data.decode()

    for expected in [
        "E0857781", "42", "camera_4",
        "90.273", "91.6", "1.327", "1.47%",
        "Order number matched", "Exceeded tolerance",
    ]:
        assert expected in body


def test_detail_page_is_fit_to_screen(client, insert_activity, today):
    activity_id = insert_activity(date=today)
    body = client.get(f"/history/activity/{activity_id}").data.decode()
    assert "page-fit-screen" in body


def test_zoomable_image_markup_present(client, app, db, today):
    """The zoom/pan container only renders when the activity has an image."""
    import os
    img_dir = os.path.join(app.config["UPLOAD_FOLDER"], today.isoformat(), "0__camera_4")
    os.makedirs(img_dir, exist_ok=True)
    img_path = os.path.join(img_dir, "zoomable.jpg")
    with open(img_path, "wb") as f:
        f.write(b"jpeg")

    activity_id = str(db["all_activities"].insert_one({
        "camera_id": 0, "camera_name": "camera_4", "activity_number": 1,
        "validation_result": "PASS", "image_path": img_path,
        "timestamp": f"{today.isoformat()}T10:00:00+00:00",
    }).inserted_id)

    body = client.get(f"/history/activity/{activity_id}").data.decode()
    assert 'id="zoom-container"' in body
    assert "zoom-hint" in body


def test_no_image_shows_placeholder_instead_of_zoom_container(client, insert_activity, today):
    activity_id = insert_activity(date=today)  # no image_path
    body = client.get(f"/history/activity/{activity_id}").data.decode()
    assert "No image available" in body
    assert 'id="zoom-container"' not in body


@pytest.mark.parametrize("bad_id", ["not-a-valid-id", "12345", "zzz"])
def test_malformed_activity_id_returns_404(client, bad_id):
    assert client.get(f"/history/activity/{bad_id}").status_code == 404


def test_nonexistent_but_valid_objectid_returns_404(client):
    assert client.get("/history/activity/6a63af2e31df6f5fb02f5c55").status_code == 404


# --- Evidence image serving ---

def test_image_inside_upload_folder_is_served(client, app, db, today):
    upload_folder = app.config["UPLOAD_FOLDER"]
    img_dir = os.path.join(upload_folder, today.isoformat(), "0__camera_4")
    os.makedirs(img_dir, exist_ok=True)
    img_path = os.path.join(img_dir, "evidence.jpg")
    with open(img_path, "wb") as f:
        f.write(b"jpeg-bytes-here")

    activity_id = str(db["all_activities"].insert_one({
        "camera_id": 0, "camera_name": "camera_4", "activity_number": 1,
        "validation_result": "PASS", "image_path": img_path,
        "timestamp": f"{today.isoformat()}T10:00:00+00:00",
    }).inserted_id)

    body = client.get(f"/history/activity/{activity_id}").data.decode()
    match = re.search(r'src="(/media/[^"]+)"', body)
    assert match, "expected an image tag pointing at /media/"

    img_resp = client.get(match.group(1))
    assert img_resp.status_code == 200
    assert img_resp.data == b"jpeg-bytes-here"


def test_image_outside_upload_folder_is_not_linked(client, db, today):
    """A path outside UPLOAD_FOLDER must not produce a servable URL."""
    activity_id = str(db["all_activities"].insert_one({
        "camera_id": 0, "camera_name": "camera_4", "activity_number": 1,
        "validation_result": "PASS", "image_path": "/etc/passwd",
        "timestamp": f"{today.isoformat()}T10:00:00+00:00",
    }).inserted_id)

    body = client.get(f"/history/activity/{activity_id}").data.decode()
    assert "No image available" in body


# --- Prev/next navigation ---

def _ids_in_time_order(insert_activity, today):
    return [
        insert_activity(activity_number=n, order_number=f"ORD{n}", date=today, hour=8 + n)
        for n in (1, 2, 3)
    ]


def test_middle_record_has_both_prev_and_next(client, insert_activity, today):
    ids = _ids_in_time_order(insert_activity, today)
    body = client.get(f"/history/activity/{ids[1]}?sort=timestamp&order=asc").data.decode()
    assert ids[0] in body
    assert ids[2] in body


def test_first_record_has_no_previous(client, insert_activity, today):
    ids = _ids_in_time_order(insert_activity, today)
    body = client.get(f"/history/activity/{ids[0]}?sort=timestamp&order=asc").data.decode()
    assert 'id="prev-link"' not in body
    assert 'id="next-link"' in body


def test_last_record_has_no_next(client, insert_activity, today):
    ids = _ids_in_time_order(insert_activity, today)
    body = client.get(f"/history/activity/{ids[2]}?sort=timestamp&order=asc").data.decode()
    assert 'id="next-link"' not in body
    assert 'id="prev-link"' in body


def test_filters_are_preserved_in_navigation_links(client, insert_activity, today):
    ids = _ids_in_time_order(insert_activity, today)
    body = client.get(
        f"/history/activity/{ids[1]}?sort=timestamp&order=asc&result=PASS"
    ).data.decode()
    assert "result=PASS" in body


def test_prev_next_respects_the_filtered_set(client, insert_activity, today):
    """Navigation walks the same filtered set the user came from, not all records."""
    pass_id = insert_activity(activity_number=1, validation_result="PASS", date=today, hour=9)
    fail_id = insert_activity(activity_number=2, validation_result="FAIL", date=today, hour=10)
    pass_id2 = insert_activity(activity_number=3, validation_result="PASS", date=today, hour=11)

    body = client.get(f"/history/activity/{pass_id}?result=PASS&sort=timestamp&order=asc").data.decode()
    assert pass_id2 in body, "next should skip to the next PASS record"
    assert fail_id not in body, "a filtered-out record must not appear in navigation"


# --- Review form ---

REVIEW_FIELDS = ["mark_discuss", "mark_ocr_wrong", "mark_process_error"]


def test_review_form_shows_all_four_controls(client, insert_activity, today):
    activity_id = insert_activity(date=today)
    body = client.get(f"/history/activity/{activity_id}").data.decode()
    assert "Marked for discussion" in body
    assert "System error" in body
    assert "Process error" in body
    assert 'name="review_comment"' in body


def test_saving_nothing_sets_result_reviewed_false(client, db, insert_activity, today):
    activity_id = insert_activity(date=today)
    client.post(f"/history/activity/{activity_id}/review", data={"query_string": ""})

    from bson import ObjectId
    doc = db["all_activities"].find_one({"_id": ObjectId(activity_id)})
    assert doc["result_reviewed"] is False
    assert doc["mark_discuss"] is None
    assert doc["mark_ocr_wrong"] is None
    assert doc["mark_process_error"] is None
    assert doc["review_comment"] == ""


@pytest.mark.parametrize("field", REVIEW_FIELDS)
@pytest.mark.parametrize("value", ["YES", "NO"])
def test_any_single_marking_sets_result_reviewed_true(
    client, db, insert_activity, today, field, value
):
    """Even an explicit "NO" counts as reviewed - it's still a decision."""
    activity_id = insert_activity(date=today)
    client.post(f"/history/activity/{activity_id}/review", data={field: value, "query_string": ""})

    from bson import ObjectId
    doc = db["all_activities"].find_one({"_id": ObjectId(activity_id)})
    assert doc["result_reviewed"] is True
    assert doc[field] == value


def test_comment_alone_sets_result_reviewed_true(client, db, insert_activity, today):
    activity_id = insert_activity(date=today)
    client.post(
        f"/history/activity/{activity_id}/review",
        data={"review_comment": "needs a look", "query_string": ""},
    )
    from bson import ObjectId
    doc = db["all_activities"].find_one({"_id": ObjectId(activity_id)})
    assert doc["result_reviewed"] is True
    assert doc["review_comment"] == "needs a look"


def test_whitespace_only_comment_does_not_count_as_reviewed(client, db, insert_activity, today):
    activity_id = insert_activity(date=today)
    client.post(
        f"/history/activity/{activity_id}/review",
        data={"review_comment": "    ", "query_string": ""},
    )
    from bson import ObjectId
    doc = db["all_activities"].find_one({"_id": ObjectId(activity_id)})
    assert doc["result_reviewed"] is False
    assert doc["review_comment"] == ""


def test_review_save_redirects_preserving_filters(client, insert_activity, today):
    activity_id = insert_activity(date=today)
    resp = client.post(
        f"/history/activity/{activity_id}/review",
        data={"mark_discuss": "YES", "query_string": "result=PASS&sort=timestamp"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "result=PASS" in resp.headers["Location"]


def test_review_save_shows_confirmation_message(client, insert_activity, today):
    activity_id = insert_activity(date=today)
    resp = client.post(
        f"/history/activity/{activity_id}/review",
        data={"mark_discuss": "YES", "query_string": ""},
        follow_redirects=True,
    )
    body = resp.data.decode()
    assert "Review saved." in body
    assert "flash-message--success" in body


def test_review_on_invalid_id_returns_404(client):
    assert client.post("/history/activity/bad-id/review", data={}).status_code == 404
