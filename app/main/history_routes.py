"""
app/main/history_routes.py
---------------------------
History table, Activity Details (with prev/next through the filtered set),
and saving the human review fields.
"""

import os
from datetime import datetime, timezone
from io import BytesIO

from bson import ObjectId
from bson.errors import InvalidId
from flask import (
    current_app, flash, redirect, render_template, request, send_file, url_for,
)
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from app.main import main_bp
from app.main.shared import base_context, query_activities
from app.utils.helpers import format_timestamp

ALLOWED_PER_PAGE = (25, 50, 100)
DEFAULT_PER_PAGE = 25

# Never export these:
#  - _id/image_path/raw_image_path: not useful in a spreadsheet, and the
#    image itself was explicitly out of scope
#  - mode: not wanted in the export
#  - api_id/api_image_path/uploaded_at: these are sync-bookkeeping fields
#    the LOCAL uploader script adds to its own copy after a successful
#    upload - they aren't meant to be business data, they just come through
#    as "extra fields, stored as-is" if a document happens to carry them.
EXPORT_EXCLUDED_FIELDS = {
    "_id", "image_path", "raw_image_path", "mode",
    "api_id", "api_image_path", "uploaded_at",
}

# Column headers that shouldn't just be the field name title-cased -
# mark_ocr_wrong is labelled "System error" everywhere else in the UI, so
# the export header should say the same thing, not "Mark Ocr Wrong".
EXPORT_HEADER_OVERRIDES = {
    "mark_ocr_wrong": "Mark System Error",
}

# Fields that hold a raw timestamp string and should be shown formatted
# (e.g. "24 Jul 2026, 22:28:48"), not MongoDB's raw ISO/BSON value.
EXPORT_DATETIME_FIELDS = {"timestamp", "created_at"}

# Preferred column order for the export - anything else found on a document
# (custom/future fields) is appended afterwards, sorted alphabetically, so
# nothing is ever silently dropped even if the schema grows.
EXPORT_PREFERRED_FIELD_ORDER = [
    "camera_id", "camera_name", "activity_number",
    "expected_order_number", "actual_order_number", "order_number_matching",
    "order_number_result", "order_number_reason",
    "expected_weight", "actual_weight", "weight_difference", "weight_difference_percent",
    "weight_result", "weight_reason",
    "validation_result", "validation_reason",
    "timestamp", "created_at",
    "mark_discuss", "mark_ocr_wrong", "mark_process_error", "review_comment", "result_reviewed",
]


@main_bp.route("/history")
def history():
    """
    History - filterable, searchable, sortable, paginated view of activity records.
    Filters (table / date range / result / ocr-wrong / has-comment) apply first,
    then search narrows the already-filtered set, then sort, then pagination.
    """
    db = current_app.extensions.get("mongo_db")
    error = None
    activities = []
    total_count = 0
    camera_options = []
    meta = {}

    try:
        per_page = int(request.args.get("per_page", DEFAULT_PER_PAGE))
    except ValueError:
        per_page = DEFAULT_PER_PAGE
    if per_page not in ALLOWED_PER_PAGE:
        per_page = DEFAULT_PER_PAGE

    try:
        page = max(int(request.args.get("page", 1)), 1)
    except ValueError:
        page = 1

    if db is None:
        error = "Database not configured."
    else:
        try:
            filtered, camera_options, meta = query_activities(db)
            total_count = len(filtered)

            start_idx = (page - 1) * per_page
            page_items = filtered[start_idx:start_idx + per_page]

            for doc in page_items:
                doc["_id"] = str(doc["_id"])
                doc["timestamp_display"] = format_timestamp(doc.get("timestamp"))

            activities = page_items
        except Exception as e:
            current_app.logger.error(f"Error fetching activities for history page: {e}")
            error = "Could not load activity history."

    total_pages = max((total_count + per_page - 1) // per_page, 1)

    context = base_context()
    context.update(meta)
    context.update({
        "activities": activities,
        "error": error,
        "camera_options": camera_options,
        "page": page,
        "per_page": per_page,
        "allowed_per_page": ALLOWED_PER_PAGE,
        "total_pages": total_pages,
        "total_count": total_count,
    })

    try:
        return render_template("main/history.html", **context)
    except Exception as e:
        current_app.logger.error(f"Error rendering history page: {e}")
        return "Something went wrong loading history.", 500


@main_bp.route("/history/export")
def export_history():
    """
    Export the CURRENTLY FILTERED set (same table/date/result/search/review
    filters as the History page, via the same query_activities() helper -
    not just the current page) to an .xlsx file. No image data - every
    other field on the activity, including the review fields (comments,
    marked-for-discussion, etc.), is included.

    The frontend shows a confirmation modal before hitting this route,
    warning that only the active filters' results will be exported - this
    route itself doesn't second-guess that; it exports whatever the query
    string says, in full (no pagination limit).
    """
    db = current_app.extensions.get("mongo_db")
    if db is None:
        return "Database not configured.", 503

    try:
        filtered, _camera_options, _meta = query_activities(db)
    except Exception as e:
        current_app.logger.error(f"Error building export data set: {e}")
        return "Something went wrong preparing the export.", 500

    # Column order: preferred fields first, then anything else found on any
    # document (alphabetical) - so a custom/future field is never silently
    # dropped, it just lands at the end instead of a fixed position.
    present_fields = set()
    for doc in filtered:
        present_fields.update(doc.keys())
    present_fields -= EXPORT_EXCLUDED_FIELDS

    if present_fields:
        ordered = [f for f in EXPORT_PREFERRED_FIELD_ORDER if f in present_fields]
        remaining = sorted(present_fields - set(ordered))
        columns = ordered + remaining
    else:
        # Zero matching activities - still produce a valid file with a
        # sensible header row (not a headerless/broken spreadsheet).
        columns = list(EXPORT_PREFERRED_FIELD_ORDER)

    wb = Workbook()
    ws = wb.active
    ws.title = "Activities"
    ws.append([
        EXPORT_HEADER_OVERRIDES.get(c, c.replace("_", " ").title())
        for c in columns
    ])

    for doc in filtered:
        row = []
        for col in columns:
            value = doc.get(col, "")
            if col in EXPORT_DATETIME_FIELDS and value:
                value = format_timestamp(value)
            elif isinstance(value, (dict, list)):
                value = str(value)  # keep exportable - Excel cells can't hold nested objects
            row.append(value)
        ws.append(row)

    for i, col in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(12, min(40, len(col) + 4))

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"activity_history_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@main_bp.route("/history/activity/<activity_id>")
def activity_detail(activity_id):
    """
    Activity details: prev/next navigation (within the same filtered+sorted set
    the person was browsing on History), evidence image in the middle, order/weight
    fields on the left, activity/reasoning fields on the right, and a review form
    below (mark for discussion, mark OCR wrong, free-text comment).
    """
    db = current_app.extensions.get("mongo_db")
    if db is None:
        return "Database not configured.", 503

    try:
        obj_id = ObjectId(activity_id)
    except InvalidId:
        return "Activity not found.", 404

    try:
        doc = db["all_activities"].find_one({"_id": obj_id})
    except Exception as e:
        current_app.logger.error(f"Error fetching activity '{activity_id}': {e}")
        return "Something went wrong loading this activity.", 500

    if doc is None:
        return "Activity not found.", 404

    # Compute prev/next within the same filtered+sorted set as History
    # (uses whatever filter query params are attached to this page's own URL).
    prev_id = next_id = None
    try:
        filtered, _, _ = query_activities(db)
        ids_in_order = [str(d["_id"]) for d in filtered]
        if activity_id in ids_in_order:
            idx = ids_in_order.index(activity_id)
            if idx > 0:
                prev_id = ids_in_order[idx - 1]
            if idx < len(ids_in_order) - 1:
                next_id = ids_in_order[idx + 1]
    except Exception as e:
        current_app.logger.warning(f"Could not compute prev/next for activity '{activity_id}': {e}")

    doc["_id"] = str(doc["_id"])
    doc["timestamp_display"] = format_timestamp(doc.get("timestamp"))

    # Build a servable URL for the evidence image, if it's inside UPLOAD_FOLDER
    image_url = None
    image_path = doc.get("image_path")
    if image_path:
        try:
            rel_path = os.path.relpath(image_path, current_app.config["UPLOAD_FOLDER"])
            if not rel_path.startswith(".."):
                image_url = url_for("main.serve_media", filepath=rel_path)
        except ValueError:
            pass  # e.g. different drive on Windows - just skip showing the image

    # Preserve the current filter/sort query string, so the "Back to History" link
    # and prev/next navigation both keep whatever filters were applied.
    query_string = request.query_string.decode()

    context = base_context()
    context.update({
        "activity": doc,
        "image_url": image_url,
        "prev_id": prev_id,
        "next_id": next_id,
        "query_string": query_string,
    })

    try:
        return render_template("main/activity_detail.html", **context)
    except Exception as e:
        current_app.logger.error(f"Error rendering activity detail page: {e}")
        return "Something went wrong loading activity details.", 500


@main_bp.route("/history/activity/<activity_id>/review", methods=["POST"])
def save_activity_review(activity_id):
    """
    Save the 4 review fields for one activity: mark_discuss (YES/NO/untouched),
    mark_ocr_wrong "System error" (YES/NO/untouched), mark_process_error
    "Process error" (YES/NO/untouched), review_comment (free text).
    result_reviewed = True if ANY of the 4 has been touched (including an explicit
    "NO"), False only if all 4 are still untouched/empty.
    """
    db = current_app.extensions.get("mongo_db")
    if db is None:
        return "Database not configured.", 503

    try:
        obj_id = ObjectId(activity_id)
    except InvalidId:
        return "Activity not found.", 404

    mark_discuss = request.form.get("mark_discuss") or None            # "YES" / "NO" / None (untouched)
    mark_ocr_wrong = request.form.get("mark_ocr_wrong") or None        # "YES" / "NO" / None (untouched)
    mark_process_error = request.form.get("mark_process_error") or None  # "YES" / "NO" / None (untouched)
    review_comment = request.form.get("review_comment", "").strip()

    result_reviewed = bool(mark_discuss or mark_ocr_wrong or mark_process_error or review_comment)

    update_fields = {
        "mark_discuss": mark_discuss,
        "mark_ocr_wrong": mark_ocr_wrong,
        "mark_process_error": mark_process_error,
        "review_comment": review_comment,
        "result_reviewed": result_reviewed,
    }

    try:
        db["all_activities"].update_one({"_id": obj_id}, {"$set": update_fields})
        flash("Review saved.", "success")
    except Exception as e:
        current_app.logger.error(f"Failed to save review for activity '{activity_id}': {e}")
        flash("Failed to save review - please try again.", "error")

    # Redirect back to the same detail page, preserving whatever filter/sort
    # query string was active (passed through as a hidden form field).
    query_string = request.form.get("query_string", "")
    target = url_for("main.activity_detail", activity_id=activity_id)
    if query_string:
        target += f"?{query_string}"
    return redirect(target)
