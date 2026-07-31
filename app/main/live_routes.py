"""
app/main/live_routes.py
------------------------
Live Monitoring: the real-time board, its JSON status endpoint, and the
lookup that bridges a live card to its full historical record.
"""

from datetime import datetime, timezone

from flask import current_app, redirect, render_template, request, jsonify, url_for

from app.main import main_bp
from app.main.shared import base_context, parse_activity_date


@main_bp.route("/live-monitoring")
def live_monitoring():
    """Live Monitoring - the board with 4 table cards, showing each table's
    latest result as received via the AI device's webhook (see app/live_status.py
    and POST /api/webhook/activity-result)."""
    from app.live_status import get_latest_status
    from app.settings_store import get_live_signal_settings
    from app.utils.helpers import format_timestamp_12h
    from app.audio_config import load_audio_config
    try:
        db = current_app.extensions.get("mongo_db")
        latest_status = get_latest_status(db)
        for data in latest_status.values():
            if data:
                data["activity_datetime_display"] = format_timestamp_12h(data.get("activity_datetime"))

        context = base_context()
        context["latest_status"] = latest_status
        context["live_details_type"] = current_app.config.get("LIVE_DETAILS_TYPE", "new_tab")
        context["live_signal_settings"] = get_live_signal_settings(db)
        context["audio_config"] = load_audio_config()
        return render_template("main/live_monitoring.html", **context)
    except Exception as e:
        current_app.logger.error(f"Error rendering live monitoring page: {e}")
        return "Something went wrong loading live monitoring.", 500


@main_bp.route("/live-status")
def live_status():
    """
    JSON snapshot of each table's latest data - kept as a manual debug/
    check endpoint (curl-friendly). The Live Monitoring page itself no
    longer polls this; it gets real-time updates via WebSocket instead
    (see app/sockets.py).
    """
    from app.live_status import get_latest_status
    from app.utils.helpers import format_timestamp_12h
    status = get_latest_status(current_app.extensions.get("mongo_db"))
    for data in status.values():
        if data:
            data["activity_datetime_display"] = format_timestamp_12h(data.get("activity_datetime"))
    return jsonify(status)


@main_bp.route("/live-monitoring/details")
def live_activity_lookup():
    """
    "View Details" from a Live Monitoring card doesn't have a MongoDB _id to
    go on directly - the webhook only gives us activity_number/order_number.
    The full record (with image) lands in all_activities separately, via the
    AI device's other upload path, which can lag a few seconds behind the
    live webhook. So: look it up by activity_number + order_number (matched
    against today's date, since this is same-day live data - avoids
    ambiguity if activity_number ever repeats across different days).

    Found -> redirect straight to the normal activity detail page.
    Not found yet -> show a "try again shortly" page instead of a hard error.
    """
    activity_number_raw = request.args.get("activity_number")
    order_number = request.args.get("order_number")
    table_id = request.args.get("table_id", "")

    try:
        activity_number = int(activity_number_raw)
    except (TypeError, ValueError):
        return "Invalid activity number.", 400

    if not order_number:
        return "Missing order number.", 400

    db = current_app.extensions.get("mongo_db")
    if db is None:
        return "Database not configured.", 503

    today = datetime.now(timezone.utc).date()
    found_doc = None

    try:
        query = {
            "activity_number": activity_number,
            "$or": [
                {"expected_order_number": order_number},
                {"actual_order_number": order_number},
            ],
        }
        for candidate in db["all_activities"].find(query):
            if parse_activity_date(candidate.get("timestamp")) == today:
                found_doc = candidate
                break
    except Exception as e:
        current_app.logger.error(f"Error looking up live activity details: {e}")
        return "Something went wrong looking up this activity.", 500

    if found_doc is not None:
        return redirect(url_for("main.activity_detail", activity_id=str(found_doc["_id"])))

    # Not uploaded to the historical record yet - show a friendly "try again" page.
    context = base_context()
    context.update({
        "table_id": table_id,
        "activity_number": activity_number,
        "order_number": order_number,
    })
    try:
        return render_template("main/live_details_pending.html", **context)
    except Exception as e:
        current_app.logger.error(f"Error rendering live-details-pending page: {e}")
        return "Details not available yet - try again shortly.", 404
