"""
History -> Export to Excel.

Covers the three things that matter most here:
  1. The export always matches the SAME filters as the History page itself
     (via the shared query_activities() helper), never just the visible page.
  2. Image data is never included.
  3. The confirmation modal is wired up so users can't be surprised by a
     partial export.
"""

import io

import openpyxl
import pytest

from app.utils.helpers import format_timestamp


def _load_export(resp):
    wb = openpyxl.load_workbook(io.BytesIO(resp.data))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    return rows[0], rows[1:]  # header, data rows


def test_export_returns_xlsx_file(client, insert_activity, today):
    insert_activity(date=today)
    resp = client.get("/history/export")
    assert resp.status_code == 200
    assert resp.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "attachment" in resp.headers.get("Content-Disposition", "")
    assert ".xlsx" in resp.headers.get("Content-Disposition", "")


def test_export_includes_all_matching_records(client, insert_activity, today):
    for n in range(1, 4):
        insert_activity(activity_number=n, order_number=f"ORD{n}", date=today)
    header, rows = _load_export(client.get("/history/export"))
    assert len(rows) == 3


def test_export_respects_result_filter(client, insert_activity, today):
    insert_activity(activity_number=1, validation_result="PASS", date=today)
    insert_activity(activity_number=2, validation_result="FAIL", date=today)
    header, rows = _load_export(client.get("/history/export?result=FAIL"))
    assert len(rows) == 1


def test_export_respects_table_filter(client, insert_activity, today):
    insert_activity(activity_number=1, camera_name="camera_4", date=today)
    insert_activity(activity_number=2, camera_name="camera_5", date=today)
    header, rows = _load_export(client.get("/history/export?table=camera_5"))
    assert len(rows) == 1


def test_export_respects_date_range(client, insert_activity, today, yesterday):
    insert_activity(activity_number=1, date=today)
    insert_activity(activity_number=2, date=yesterday)
    header, rows = _load_export(client.get("/history/export"))  # default = today only
    assert len(rows) == 1


def test_export_ignores_pagination_exports_everything_matching(client, insert_activity, today):
    """The whole point of export vs. the on-screen table: no page limit."""
    for n in range(1, 31):
        insert_activity(activity_number=n, order_number=f"ORD{n}", date=today)
    header, rows = _load_export(client.get("/history/export?per_page=25&page=1"))
    assert len(rows) == 30


def test_export_excludes_image_fields(client, insert_activity, today):
    insert_activity(date=today, image_path="/secret/photo.jpg", raw_image_path="/secret/raw.jpg")
    header, rows = _load_export(client.get("/history/export"))
    assert "Image Path" not in header
    assert "Raw Image Path" not in header
    assert "Id" not in header and "_Id" not in header


def test_export_includes_review_fields(client, insert_activity, today):
    insert_activity(
        date=today,
        mark_discuss="YES",
        mark_ocr_wrong="NO",
        mark_process_error=None,
        review_comment="Needs a second look",
        result_reviewed=True,
    )
    header, rows = _load_export(client.get("/history/export"))
    assert "Mark Discuss" in header
    assert "Review Comment" in header
    assert "Result Reviewed" in header
    comment_col = header.index("Review Comment")
    assert rows[0][comment_col] == "Needs a second look"


def test_mark_ocr_wrong_header_is_relabeled(client, insert_activity, today):
    """
    mark_ocr_wrong is labelled "System error" everywhere else in the app -
    the export header must match, not the auto-generated "Mark Ocr Wrong".
    """
    insert_activity(date=today, mark_ocr_wrong="YES")
    header, rows = _load_export(client.get("/history/export"))
    assert "Mark System Error" in header
    assert "Mark Ocr Wrong" not in header


def test_mode_column_is_excluded(client, insert_activity, today):
    insert_activity(date=today, mode="MONITORING")
    header, rows = _load_export(client.get("/history/export"))
    assert "Mode" not in header


def test_uploader_bookkeeping_fields_are_excluded(client, insert_activity, today):
    """
    api_id/api_image_path/uploaded_at are added by the LOCAL uploader script
    to its own copy after a successful sync - they're sync metadata, not
    business data, and must never appear in the export even if a document
    happens to carry them through as "extra fields".
    """
    insert_activity(
        date=today,
        api_id="abc123",
        api_image_path="/some/path.jpg",
        uploaded_at="2026-07-24T22:30:00+00:00",
    )
    header, rows = _load_export(client.get("/history/export"))
    assert "Api Id" not in header
    assert "Api Image Path" not in header
    assert "Uploaded At" not in header


def test_timestamp_and_created_at_are_formatted_not_raw(client, insert_activity, today):
    """The raw ISO/MongoDB value must never reach the spreadsheet - it should
    read like every other date shown elsewhere in the app."""
    insert_activity(
        date=today,
        hour=22,
        created_at=f"{today.isoformat()}T22:28:50+00:00",
    )
    header, rows = _load_export(client.get("/history/export"))
    ts_value = rows[0][header.index("Timestamp")]
    created_value = rows[0][header.index("Created At")]
    assert "T" not in str(ts_value)         # no raw ISO separator
    assert "+00:00" not in str(ts_value)    # no raw offset
    assert ts_value == format_timestamp(f"{today.isoformat()}T22:00:00+00:00")
    assert created_value == format_timestamp(f"{today.isoformat()}T22:28:50+00:00")


def test_export_handles_zero_matches_gracefully(client):
    """An empty result set should still produce a valid (header-only) file, not crash."""
    resp = client.get("/history/export?table=nonexistent_camera")
    assert resp.status_code == 200
    header, rows = _load_export(resp)
    assert rows == []


@pytest.mark.parametrize("bad_query", ["start_date=garbage", "per_page=99999", "sort=nonexistent_field"])
def test_export_does_not_crash_on_odd_query_params(client, insert_activity, today, bad_query):
    insert_activity(date=today)
    resp = client.get(f"/history/export?{bad_query}")
    assert resp.status_code == 200


# --- Confirmation modal wiring ---

def test_export_button_and_modal_present_when_there_are_results(client, insert_activity, today):
    insert_activity(date=today)
    body = client.get("/history").data.decode()
    assert 'id="export-btn"' in body
    assert 'id="export-modal"' in body
    assert "current filters" in body
    assert "js/history.js" in body


def test_export_button_hidden_when_no_results(client):
    """Nothing to export - the button and modal shouldn't render at all."""
    body = client.get("/history?table=nonexistent_camera").data.decode()
    assert 'id="export-btn"' not in body
    assert 'id="export-modal"' not in body


def test_export_button_carries_the_export_url(client, insert_activity, today):
    insert_activity(date=today)
    body = client.get("/history").data.decode()
    assert 'data-export-url="/history/export"' in body


def test_modal_shows_the_current_record_count(client, insert_activity, today):
    for n in range(1, 4):
        insert_activity(activity_number=n, date=today)
    body = client.get("/history").data.decode()
    assert '<strong id="export-modal-count">3</strong>' in body
