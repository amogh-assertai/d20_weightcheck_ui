"""
app/api/routes.py
-------------------
Two endpoints for the AI device:

1. POST /activities - full activity metadata + evidence image, persisted to
   MongoDB. The one source of truth for history.

2. POST /webhook/activity-result - lightweight fire-and-forget webhook, just
   the latest result per table, for live display on the Live Monitoring page
   only. NOT persisted to MongoDB - separate mechanism, separate purpose
   (matches how the AI team described it: validation-result delivery is a
   distinct webhook from the full activity+image ingestion).
"""

import os
import json
from datetime import datetime, timezone
from bson import ObjectId
from bson.errors import InvalidId
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from pymongo.errors import PyMongoError
from app.live_status import check_is_duplicate, persist_result, VALID_TABLE_IDS, REQUIRED_FIELDS
from app.sockets import broadcast_table_update
from app.main.shared import parse_activity_date

api_bp = Blueprint("api", __name__)


def _resolve_date_folder(activity_data):
    """
    Decide which date folder to store the image under.
    Prefers the activity's own 'timestamp' field (the actual event date),
    falls back to today's date if it's missing or not parseable.
    """
    timestamp_value = activity_data.get("timestamp")
    if timestamp_value:
        try:
            # Accepts ISO 8601, including a trailing 'Z'
            parsed = datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00"))
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            current_app.logger.warning(
                f"Could not parse timestamp '{timestamp_value}' - falling back to today's date"
            )
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@api_bp.route("/activities", methods=["POST"])
def receive_activity():
    """
    Expects multipart/form-data with:
      - 'activity_data': a JSON string (the activity metadata)
      - 'image': the evidence image file
    """
    # --- Validate the image file is present ---
    if "image" not in request.files:
        return jsonify({"error": "Missing 'image' file in request"}), 400

    image_file = request.files["image"]
    if image_file.filename == "":
        return jsonify({"error": "No image file selected"}), 400

    # --- Validate and parse activity_data ---
    raw_activity_data = request.form.get("activity_data")
    if not raw_activity_data:
        return jsonify({"error": "Missing 'activity_data' form field"}), 400

    try:
        activity_data = json.loads(raw_activity_data)
    except (json.JSONDecodeError, TypeError):
        return jsonify({"error": "'activity_data' must be valid JSON"}), 400

    # camera_id/camera_name are needed to build the folder structure - required here.
    camera_id = activity_data.get("camera_id")
    camera_name = activity_data.get("camera_name")
    if camera_id is None or not camera_name:
        return jsonify({"error": "activity_data must include 'camera_id' and 'camera_name'"}), 400

    # --- Build the storage path: uploads/{date}/{camera_id}__{camera_name}/ ---
    date_folder = _resolve_date_folder(activity_data)
    table_folder = f"{camera_id}__{camera_name}"
    target_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], date_folder, table_folder)

    try:
        os.makedirs(target_dir, exist_ok=True)
    except OSError as e:
        current_app.logger.error(f"Could not create upload directory '{target_dir}': {e}")
        return jsonify({"error": "Failed to prepare storage location"}), 500

    # --- Build a safe, collision-resistant filename ---
    original_name = secure_filename(image_file.filename)
    activity_number = activity_data.get("activity_number", "na")
    unique_prefix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    stored_filename = f"{camera_id}__{activity_number}__{unique_prefix}__{original_name}"
    absolute_path = os.path.join(target_dir, stored_filename)

    try:
        image_file.save(absolute_path)
    except OSError as e:
        current_app.logger.error(f"Could not save uploaded image to '{absolute_path}': {e}")
        return jsonify({"error": "Failed to save image"}), 500

    # --- Store the image path in the document, then insert into MongoDB ---
    activity_data["image_path"] = absolute_path

    db = current_app.extensions.get("mongo_db")
    if db is None:
        current_app.logger.error("Ingestion failed: MongoDB not configured/reachable")
        return jsonify({"error": "Storage backend unavailable"}), 503

    try:
        result = db["all_activities"].insert_one(activity_data)
        current_app.logger.info(
            f"Stored activity #{activity_number} from {camera_name} "
            f"(image: {stored_filename})"
        )
        return jsonify({
            "status": "stored",
            "id": str(result.inserted_id),
            "image_path": absolute_path,
        }), 201
    except PyMongoError as e:
        current_app.logger.error(f"MongoDB insert failed: {e}")
        return jsonify({"error": "Failed to store activity"}), 503
    except Exception as e:
        current_app.logger.error(f"Unexpected error storing activity: {e}")
        return jsonify({"error": "Unexpected server error"}), 500


@api_bp.route("/webhook/activity-result", methods=["POST"])
def receive_activity_result():
    """
    Lightweight fire-and-forget webhook: latest data for one table.
    Expects JSON:
      {"table_id": "table_1", "result": "PASS", "activity_number": 42,
       "activity_datetime": "2026-07-28T10:15:00+00:00", "order_number": "E0857781"}

    Order of operations (deliberate): if this is genuinely new data (not an
    exact repeat), broadcast it to every connected browser client via
    WebSocket FIRST - that's the time-critical part, since it drives the
    live blink (and future audio) that should sync to the real detection
    moment as closely as possible. Persisting to MongoDB happens right
    after, since that part isn't time-sensitive for the live display.

    Separate from POST /activities, which remains the full historical
    record (with image), uploaded independently by the AI device.
    """
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    table_id = payload.get("table_id")
    if not table_id or table_id not in VALID_TABLE_IDS:
        return jsonify({"error": f"'table_id' must be one of {list(VALID_TABLE_IDS)}"}), 400

    missing = [f for f in REQUIRED_FIELDS if payload.get(f) is None]
    if missing:
        return jsonify({"error": f"Missing required field(s): {', '.join(missing)}"}), 400

    result = payload.get("result")
    activity_number = payload.get("activity_number")
    activity_datetime = payload.get("activity_datetime")
    order_number = payload.get("order_number")

    db = current_app.extensions.get("mongo_db")

    if check_is_duplicate(db, table_id, result, activity_number):
        current_app.logger.info(
            f"Duplicate for {table_id}: activity #{activity_number} ({result}) "
            f"already stored - ignored, no re-signal sent"
        )
        return jsonify({"status": "duplicate_ignored", "table_id": table_id, "result": result}), 200

    data = {
        "result": result,
        "activity_number": activity_number,
        "activity_datetime": activity_datetime,
        "order_number": order_number,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    # 1. Push to every connected browser FIRST - time-critical (blink/audio sync).
    broadcast_table_update(table_id, data)

    # 2. THEN persist to MongoDB - not time-sensitive for the live display.
    persist_result(db, table_id, data)

    current_app.logger.info(
        f"Recorded NEW latest data for {table_id}: {result} (activity #{activity_number})"
    )
    return jsonify({"status": "recorded", "table_id": table_id, "result": result}), 200


VALID_ERROR_TYPES = {"SYSTEM_ERROR", "PROCESS_ERROR", "BOTH", "ALL_OK"}


@api_bp.route("/activities", methods=["GET"])
def list_activities():
    """
    Read/export endpoint for external systems - one flexible query, every
    filter below is optional and combinable:

      start_date, end_date   - YYYY-MM-DD (both default to today if neither given)
      camera_id               - exact match
      result                   - validation_result exact match (PASS/FAIL/
                                 MISSING_DATA/etc.) - deliberately NOT
                                 restricted to a fixed list, so a new result
                                 type is queryable immediately, same
                                 philosophy as the History page's filter
      error_type               - SYSTEM_ERROR / PROCESS_ERROR / BOTH / ALL_OK
      order_number             - matches either expected_order_number or
                                 actual_order_number
      has_comment              - "present" or "absent"
      saved_for_active_learning - "true" or "false". This field is only
                                 ever set to True or removed entirely (see
                                 toggle_active_learning below) - never
                                 stored as False - so "false" here matches
                                 "field doesn't exist", not a stored False.

    No pagination (by explicit choice) - returns every matching record in
    one response: {"count": N, "activities": [...]}. Documents are returned
    as-is (including image_path and raw timestamps) - this is a machine-
    consumed endpoint, so no human-readability formatting is applied here
    (unlike the History page's Excel export, which does format dates for
    a person reading a spreadsheet).
    """
    db = current_app.extensions.get("mongo_db")
    if db is None:
        return jsonify({"error": "Storage backend unavailable"}), 503

    today = datetime.now(timezone.utc).date()

    def _parse_date_param(value, param_name, default):
        if not value:
            return default, None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date(), None
        except ValueError:
            return None, f"'{param_name}' must be in YYYY-MM-DD format"

    start_date, err = _parse_date_param(request.args.get("start_date"), "start_date", today)
    if err:
        return jsonify({"error": err}), 400
    end_date, err = _parse_date_param(request.args.get("end_date"), "end_date", today)
    if err:
        return jsonify({"error": err}), 400
    if start_date > end_date:
        return jsonify({"error": "'start_date' must not be after 'end_date'"}), 400

    camera_id_param = request.args.get("camera_id")
    result_param = request.args.get("result")
    error_type_param = request.args.get("error_type")
    order_number_param = request.args.get("order_number")
    has_comment_param = request.args.get("has_comment")
    active_learning_param = request.args.get("saved_for_active_learning")

    if error_type_param is not None and error_type_param not in VALID_ERROR_TYPES:
        return jsonify({"error": f"'error_type' must be one of {sorted(VALID_ERROR_TYPES)}"}), 400
    if has_comment_param is not None and has_comment_param not in ("present", "absent"):
        return jsonify({"error": "'has_comment' must be 'present' or 'absent'"}), 400
    if active_learning_param is not None and active_learning_param.lower() not in ("true", "false"):
        return jsonify({"error": "'saved_for_active_learning' must be 'true' or 'false'"}), 400

    # Built as a list of independent conditions, combined with $and only if
    # there's more than one - avoids two top-level $or keys silently
    # clobbering each other in a single dict (e.g. order_number + has_comment
    # both need their own $or).
    conditions = []

    if camera_id_param is not None:
        try:
            camera_id_value = int(camera_id_param)
        except ValueError:
            camera_id_value = camera_id_param  # fall back to string match rather than error
        conditions.append({"camera_id": camera_id_value})

    if result_param is not None:
        conditions.append({"validation_result": result_param})

    if error_type_param is not None:
        conditions.append({"error_type": error_type_param})

    if order_number_param is not None:
        conditions.append({"$or": [
            {"expected_order_number": order_number_param},
            {"actual_order_number": order_number_param},
        ]})

    if has_comment_param == "present":
        conditions.append({"review_comment": {"$exists": True, "$nin": ["", None]}})
    elif has_comment_param == "absent":
        conditions.append({"$or": [
            {"review_comment": {"$exists": False}},
            {"review_comment": None},
            {"review_comment": ""},
        ]})

    if active_learning_param is not None:
        if active_learning_param.lower() == "true":
            # saved_for_active_learning is only ever set to True or removed
            # entirely (see toggle_active_learning) - never stored as False.
            conditions.append({"saved_for_active_learning": True})
        else:
            conditions.append({"saved_for_active_learning": {"$exists": False}})

    if len(conditions) > 1:
        mongo_query = {"$and": conditions}
    elif conditions:
        mongo_query = conditions[0]
    else:
        mongo_query = {}

    try:
        docs = list(db["all_activities"].find(mongo_query))
    except PyMongoError as e:
        current_app.logger.error(f"MongoDB query failed for GET /api/activities: {e}")
        return jsonify({"error": "Failed to query activities"}), 503

    # Date-range filtering happens in Python, same as every other page in
    # this app - timestamp is stored as a string, not a native Mongo date.
    activities = []
    for doc in docs:
        doc_date = parse_activity_date(doc.get("timestamp"))
        if doc_date is not None and not (start_date <= doc_date <= end_date):
            continue
        doc["_id"] = str(doc["_id"])
        activities.append(doc)

    return jsonify({"count": len(activities), "activities": activities}), 200


@api_bp.route("/activities/<activity_id>", methods=["PATCH"])
def update_activity(activity_id):
    """
    Update a single activity by its _id - built for the VLM verification
    system to write back its findings.

    JSON body (all fields optional, but at least one is required):
      {
        "error_type": "ALL_OK",       # or "PROCESS_ERROR", "SYSTEM_ERROR", "BOTH"
        "no_of_pages": 3,
        "no_of_items": 12
      }

    error_type_marked_by is ALWAYS set to "AI" here - it's implicit in
    calling this endpoint, not something the caller supplies, so there's no
    way to call this and have it show as a human review by mistake. The
    human-facing review form (History/Activity Details) is a completely
    separate code path that always writes "VERIFICATION_TEAM" instead - the
    two can never collide or impersonate each other.

    Every CHANGE to error_type is appended to error_type_history (source:
    "ai") - re-sending the same value doesn't create a duplicate entry,
    same rule as the human review path.

    result_reviewed is recomputed after applying whatever this call
    changed, using the same formula as everywhere else in the app:
    mark_discuss OR error_type OR review_comment.

    Currently the VLM is only expected to send ALL_OK or PROCESS_ERROR
    (per how it's being used), but SYSTEM_ERROR and BOTH are also accepted
    here - this endpoint doesn't assume anything about which subset of the
    4 values any given caller will actually use.
    """
    db = current_app.extensions.get("mongo_db")
    if db is None:
        return jsonify({"error": "Storage backend unavailable"}), 503

    try:
        obj_id = ObjectId(activity_id)
    except InvalidId:
        return jsonify({"error": "Activity not found"}), 404

    payload = request.get_json(silent=True)
    if payload is None or not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    existing = db["all_activities"].find_one({"_id": obj_id})
    if existing is None:
        return jsonify({"error": "Activity not found"}), 404

    update_fields = {}
    updated_field_names = []

    if "error_type" in payload:
        new_error_type = payload["error_type"]
        if new_error_type not in VALID_ERROR_TYPES:
            return jsonify({"error": f"'error_type' must be one of {sorted(VALID_ERROR_TYPES)}"}), 400
        update_fields["error_type"] = new_error_type
        update_fields["error_type_marked_by"] = "AI"
        updated_field_names.append("error_type")

    for count_field in ("no_of_pages", "no_of_items"):
        if count_field in payload:
            value = payload[count_field]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return jsonify({"error": f"'{count_field}' must be a non-negative integer"}), 400
            update_fields[count_field] = value
            updated_field_names.append(count_field)

    if not update_fields:
        return jsonify({
            "error": "No recognized fields to update - expected at least one of: "
                     "error_type, no_of_pages, no_of_items"
        }), 400

    # result_reviewed uses the same formula as the human review path
    # (app/main/history_routes.py::save_activity_review) - recomputed here
    # using whatever error_type this call ends up with (new or existing).
    effective_error_type = update_fields.get("error_type", existing.get("error_type"))
    mark_discuss = existing.get("mark_discuss")
    review_comment = (existing.get("review_comment") or "").strip()
    update_fields["result_reviewed"] = bool(mark_discuss or effective_error_type or review_comment)

    update_op = {"$set": update_fields}

    previous_error_type = existing.get("error_type")
    if "error_type" in update_fields and update_fields["error_type"] != previous_error_type:
        update_op["$push"] = {
            "error_type_history": {
                "value": update_fields["error_type"],
                "marked_by": "AI",
                "marked_at": datetime.now(timezone.utc).isoformat(),
                "source": "ai",
            }
        }

    try:
        db["all_activities"].update_one({"_id": obj_id}, update_op)
    except PyMongoError as e:
        current_app.logger.error(f"MongoDB update failed for activity '{activity_id}': {e}")
        return jsonify({"error": "Failed to update activity"}), 503

    current_app.logger.info(f"AI-updated activity {activity_id}: {', '.join(updated_field_names)}")
    return jsonify({"status": "updated", "id": activity_id, "updated_fields": updated_field_names}), 200


@api_bp.route("/activities/clear-active-learning", methods=["POST"])
def clear_active_learning():
    """
    Bulk-clears saved_for_active_learning from EVERY activity that
    currently has it set. Removes the field entirely ($unset), matching
    the same rule as the single-activity toggle in
    app/main/history_routes.py::toggle_active_learning - "not saved" and
    "field doesn't exist" are the same state, never a stored False.

    No request body needed. Intended for a periodic/manual bulk cleanup
    after a batch of images has been pulled for active learning - not
    something a single-activity workflow should ever need to call.
    """
    db = current_app.extensions.get("mongo_db")
    if db is None:
        return jsonify({"error": "Storage backend unavailable"}), 503

    try:
        result = db["all_activities"].update_many(
            {"saved_for_active_learning": {"$exists": True}},
            {"$unset": {"saved_for_active_learning": ""}},
        )
    except PyMongoError as e:
        current_app.logger.error(f"Failed to bulk-clear active learning flags: {e}")
        return jsonify({"error": "Failed to clear active learning flags"}), 503

    current_app.logger.info(f"Cleared saved_for_active_learning from {result.modified_count} activity(ies)")
    return jsonify({"status": "cleared", "cleared_count": result.modified_count}), 200