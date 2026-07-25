"""
app/api/routes.py
-------------------
REST ingestion endpoint. A local script uploads one activity's metadata
(as JSON) together with its evidence image (as a file) in a single
multipart/form-data request. This endpoint:
  1. Saves the image to disk under uploads/{date}/{table}/
  2. Stores the image path inside the activity document
  3. Inserts that document into MongoDB

Scope: exactly this one endpoint - nothing else (no auth, no listing route,
no extra validation beyond what's needed to build the file path safely).
"""

import os
import json
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from pymongo.errors import PyMongoError

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
