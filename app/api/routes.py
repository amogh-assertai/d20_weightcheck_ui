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
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from pymongo.errors import PyMongoError
from app.live_status import check_is_duplicate, persist_result, VALID_TABLE_IDS, REQUIRED_FIELDS
from app.sockets import broadcast_table_update

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
