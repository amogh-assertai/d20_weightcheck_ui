"""
app/main/routes.py
-------------------
Blueprint for general UI pages: Home, Live Monitoring, Settings, History,
Activity Details (with prev/next + review form), and evidence-image serving.
"""

import os
from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint, render_template, current_app, request, send_from_directory, url_for, redirect, flash, jsonify
)
from bson import ObjectId
from bson.errors import InvalidId

main_bp = Blueprint("main", __name__, template_folder="../templates/main")

ALLOWED_PER_PAGE = (25, 50, 100)
DEFAULT_PER_PAGE = 25


def _base_context():
    """Shared template variables used by every page in this blueprint."""
    return {
        "app_name": current_app.config["APP_NAME"],
        "client_name": current_app.config["CLIENT_NAME"],
        "max_clients": current_app.config["MAX_CLIENTS"],
    }


def _parse_activity_date(timestamp_value):
    """Parse an activity's ISO timestamp string into just its date, or None if unparseable."""
    if not timestamp_value:
        return None
    try:
        return datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _format_timestamp(timestamp_value):
    """Human-readable timestamp for display - delegates to the shared helper
    (app/utils/helpers.py) so this page's formatting matches what the
    WebSocket broadcast payload uses too."""
    from app.utils.helpers import format_timestamp
    return format_timestamp(timestamp_value)


def _parse_percent(value):
    """Parse a numeric string, optionally with a trailing '%' (e.g. '24.23%' or '9.800'), into a float. Returns None if not parseable."""
    if value is None:
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except ValueError:
        return None


def _sort_key(doc, field):
    """
    Sort key that handles numeric-looking values (weights, percentages stored as
    strings like '24.23%') and falls back to case-insensitive text sorting for
    everything else (camera names, order numbers, ISO timestamp strings).
    """
    value = doc.get(field, "")
    try:
        cleaned = str(value).replace("%", "").strip()
        return (0, float(cleaned))
    except (TypeError, ValueError):
        return (1, str(value).lower())


def _query_activities(db):
    """
    Shared filter/search/sort logic used by both the History page and the
    Activity Detail page's prev/next navigation, so both always agree on
    "what's in the current filtered set" and in what order.
    Reads all filter/search/sort values from request.args.
    """
    table_filter = request.args.get("table", "all")
    result_filter = request.args.get("result", "all")
    search_term = request.args.get("search", "").strip()
    ocr_wrong_filter = request.args.get("ocr_wrong", "all")   # "all" / "YES" / "NO"
    discuss_filter = request.args.get("discuss", "all")       # "all" / "YES" / "NO"
    has_comment_filter = request.args.get("has_comment", "all")  # "all" / "present" / "absent"
    sort_field = request.args.get("sort", "timestamp")
    sort_order = request.args.get("order", "desc")

    today = datetime.now(timezone.utc).date()
    default_start = today
    start_date_str = request.args.get("start_date", default_start.isoformat())
    end_date_str = request.args.get("end_date", today.isoformat())

    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        start_date = default_start
        start_date_str = start_date.isoformat()

    try:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except ValueError:
        end_date = today
        end_date_str = end_date.isoformat()

    camera_options = []
    filtered = []

    if db is not None:
        camera_options = sorted(db["all_activities"].distinct("camera_name"))

        # Mongo-side filter: fields that are simple exact matches
        mongo_query = {}
        if table_filter != "all":
            mongo_query["camera_name"] = table_filter
        if result_filter != "all":
            mongo_query["validation_result"] = result_filter
        if ocr_wrong_filter in ("YES", "NO"):
            mongo_query["mark_ocr_wrong"] = ocr_wrong_filter
        if discuss_filter in ("YES", "NO"):
            mongo_query["mark_discuss"] = discuss_filter
        if has_comment_filter == "present":
            mongo_query["review_comment"] = {"$exists": True, "$nin": ["", None]}
        elif has_comment_filter == "absent":
            mongo_query["$or"] = [
                {"review_comment": {"$exists": False}},
                {"review_comment": ""},
                {"review_comment": None},
            ]

        all_matching = list(db["all_activities"].find(mongo_query))

        # Date range + text search applied in Python - timestamps are stored as
        # ISO strings (not native Mongo dates), so parsing here is more robust
        # than a string-range Mongo query.
        for doc in all_matching:
            doc_date = _parse_activity_date(doc.get("timestamp"))
            if doc_date is not None and not (start_date <= doc_date <= end_date):
                continue

            if search_term:
                haystack = " ".join(str(doc.get(f, "")) for f in
                                     ["expected_order_number", "actual_order_number", "activity_number"])
                if search_term.lower() not in haystack.lower():
                    continue

            filtered.append(doc)

        filtered.sort(key=lambda d: _sort_key(d, sort_field), reverse=(sort_order == "desc"))

    meta = {
        "selected_table": table_filter,
        "selected_result": result_filter,
        "search_term": search_term,
        "selected_ocr_wrong": ocr_wrong_filter,
        "selected_has_comment": has_comment_filter,
        "selected_discuss": discuss_filter,
        "selected_sort": sort_field,
        "selected_order": sort_order,
        "start_date": start_date_str,
        "end_date": end_date_str,
    }
    return filtered, camera_options, meta


@main_bp.route("/")
def home():
    """Home page - kept empty/minimal for now, content lives on other pages."""
    try:
        return render_template("main/home.html", **_base_context())
    except Exception as e:
        current_app.logger.error(f"Error rendering home page: {e}")
        return "Something went wrong loading the home page.", 500


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

        context = _base_context()
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
            if _parse_activity_date(candidate.get("timestamp")) == today:
                found_doc = candidate
                break
    except Exception as e:
        current_app.logger.error(f"Error looking up live activity details: {e}")
        return "Something went wrong looking up this activity.", 500

    if found_doc is not None:
        return redirect(url_for("main.activity_detail", activity_id=str(found_doc["_id"])))

    # Not uploaded to the historical record yet - show a friendly "try again" page.
    context = _base_context()
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


@main_bp.route("/health")
def health():
    """Health check endpoint for CI/CD and uptime monitoring."""
    return "OK", 200


@main_bp.route("/settings", methods=["GET", "POST"])
def settings():
    """Settings - currently controls the Live Monitoring signal behaviour
    (blink/solid pattern, duration, whether color is retained after a blink)."""
    from app.settings_store import get_live_signal_settings, save_live_signal_settings

    db = current_app.extensions.get("mongo_db")

    if request.method == "POST":
        pattern = request.form.get("pattern", "blink")
        if pattern not in ("blink", "solid"):
            pattern = "blink"

        try:
            duration_sec = float(request.form.get("duration_sec", 5))
        except (TypeError, ValueError):
            duration_sec = 5
        duration_sec = max(1, min(duration_sec, 60))  # sane bounds: 1-60 sec

        retain_color = request.form.get("retain_color") == "on"

        if save_live_signal_settings(db, pattern, duration_sec, retain_color):
            flash("Settings saved.", "success")
        else:
            flash("Could not save settings - database unavailable.", "error")

        return redirect(url_for("main.settings"))

    try:
        context = _base_context()
        context["live_signal_settings"] = get_live_signal_settings(db)
        return render_template("main/settings.html", **context)
    except Exception as e:
        current_app.logger.error(f"Error rendering settings page: {e}")
        return "Something went wrong loading settings.", 500


@main_bp.route("/analytics")
def analytics():
    """Analytics section landing - redirects to the first sub-page (System Analytics)."""
    return redirect(url_for("main.analytics_system"))


@main_bp.route("/analytics/system")
def analytics_system():
    """
    System Analytics: activity volume, camera-wise distribution, PASS/FAIL/
    MISSING_DATA breakdown, and top-10 highest weight differences - all
    scoped to a date range (defaults to today only).
    """
    db = current_app.extensions.get("mongo_db")
    error = None
    total_count = 0
    pass_count = fail_count = missing_count = 0
    camera_distribution = []
    top_weight_diff = []

    today = datetime.now(timezone.utc).date()
    start_date_str = request.args.get("start_date", today.isoformat())
    end_date_str = request.args.get("end_date", today.isoformat())

    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        start_date = today
        start_date_str = today.isoformat()

    try:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    except ValueError:
        end_date = today
        end_date_str = today.isoformat()

    if db is None:
        error = "Database not configured."
    else:
        try:
            all_docs = list(db["all_activities"].find({}))
            filtered = []
            for doc in all_docs:
                doc_date = _parse_activity_date(doc.get("timestamp"))
                if doc_date is not None and not (start_date <= doc_date <= end_date):
                    continue
                filtered.append(doc)

            total_count = len(filtered)

            # Per-camera breakdown: total + PASS/FAIL/MISSING_DATA/other counts,
            # so each camera's result composition is visible, not just its volume.
            camera_stats = {}
            for doc in filtered:
                cam = doc.get("camera_name", "Unknown")
                stats = camera_stats.setdefault(
                    cam, {"total": 0, "pass": 0, "fail": 0, "missing": 0, "other": 0}
                )
                stats["total"] += 1

                result = doc.get("validation_result")
                if result == "PASS":
                    stats["pass"] += 1
                    pass_count += 1
                elif result == "FAIL":
                    stats["fail"] += 1
                    fail_count += 1
                elif result == "MISSING_DATA":
                    stats["missing"] += 1
                    missing_count += 1
                else:
                    stats["other"] += 1

            camera_distribution = sorted(camera_stats.items(), key=lambda kv: kv[1]["total"], reverse=True)

            # Top 5 highest ABSOLUTE weight difference - only among docs where
            # weight_difference actually parses as a number (can't meaningfully
            # rank the rest). Ranked by the raw difference, not the percentage.
            candidates = []
            for doc in filtered:
                diff = _parse_percent(doc.get("weight_difference"))
                if diff is not None:
                    candidates.append((abs(diff), doc))
            candidates.sort(key=lambda t: t[0], reverse=True)

            for diff, doc in candidates[:5]:
                top_weight_diff.append({
                    "_id": str(doc["_id"]),
                    "camera_name": doc.get("camera_name", "-"),
                    "activity_number": doc.get("activity_number", "-"),
                    "order_number": doc.get("actual_order_number", doc.get("expected_order_number", "-")),
                    "expected_weight": doc.get("expected_weight", "-"),
                    "actual_weight": doc.get("actual_weight", "-"),
                    "weight_difference": doc.get("weight_difference", "-"),
                    "weight_difference_percent": doc.get("weight_difference_percent", "-"),
                })
        except Exception as e:
            current_app.logger.error(f"Error computing system analytics: {e}")
            error = "Could not load analytics."

    def pct_of(n):
        return round((n / total_count * 100), 1) if total_count else 0.0

    context = _base_context()
    context.update({
        "error": error,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "total_count": total_count,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "missing_count": missing_count,
        "pass_pct": pct_of(pass_count),
        "fail_pct": pct_of(fail_count),
        "missing_pct": pct_of(missing_count),
        "camera_distribution": camera_distribution,
        "top_weight_diff": top_weight_diff,
    })

    try:
        return render_template("main/analytics_system.html", **context)
    except Exception as e:
        current_app.logger.error(f"Error rendering analytics page: {e}")
        return "Something went wrong loading analytics.", 500


@main_bp.route("/analytics/accuracy")
def analytics_accuracy():
    """
    Accuracy Analytics - a dynamic metric that depends on ongoing human
    review of FAIL/MISSING_DATA activities (System Error / Process Error
    markings), NOT a fixed number. See the calculation breakdown rendered
    directly on the page - the formula and every intermediate count are
    shown, not just the final percentage, since this changes as review
    progresses.

    Rules (also explained on the page itself):
    - PASS is always counted as correct.
    - FAIL/MISSING_DATA is only included if at least one of System Error /
      Process Error has been marked (Yes or No) - if both are still
      untouched, it's excluded (pending review).
    - Of the reviewed ones: System Error = Yes -> incorrect. Process Error
      = Yes, or both marked No -> correct.
    - If both are marked Yes on the same activity, System Error takes
      priority (counted as incorrect).
    """
    db = current_app.extensions.get("mongo_db")
    error = None

    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    selected_date_str = request.args.get("date", yesterday.isoformat())
    try:
        selected_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
    except ValueError:
        selected_date = yesterday
        selected_date_str = yesterday.isoformat()

    total_count = pass_count = fail_count = missing_count = 0
    reviewed_non_pass = unmarked_non_pass = system_error_count = correct_non_pass = 0

    if db is None:
        error = "Database not configured."
    else:
        try:
            for doc in db["all_activities"].find({}):
                if _parse_activity_date(doc.get("timestamp")) != selected_date:
                    continue

                total_count += 1
                result = doc.get("validation_result")

                if result == "PASS":
                    pass_count += 1
                    continue
                elif result == "FAIL":
                    fail_count += 1
                elif result == "MISSING_DATA":
                    missing_count += 1
                else:
                    continue  # unexpected/other value - not part of the pass/fail/missing buckets

                system_error = doc.get("mark_ocr_wrong")
                process_error = doc.get("mark_process_error")

                if system_error is None and process_error is None:
                    unmarked_non_pass += 1
                else:
                    reviewed_non_pass += 1
                    if system_error == "YES":
                        system_error_count += 1
                    else:
                        correct_non_pass += 1
        except Exception as e:
            current_app.logger.error(f"Error computing accuracy analytics: {e}")
            error = "Could not load accuracy analytics."

    non_pass_count = fail_count + missing_count
    evaluated_total = pass_count + reviewed_non_pass
    correct_total = pass_count + correct_non_pass
    accuracy_pct = round((correct_total / evaluated_total * 100), 1) if evaluated_total else None
    pending_pct = round((unmarked_non_pass / non_pass_count * 100), 1) if non_pass_count else 0.0

    context = _base_context()
    context.update({
        "error": error,
        "selected_date": selected_date_str,
        "total_count": total_count,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "missing_count": missing_count,
        "non_pass_count": non_pass_count,
        "reviewed_non_pass": reviewed_non_pass,
        "unmarked_non_pass": unmarked_non_pass,
        "system_error_count": system_error_count,
        "correct_non_pass": correct_non_pass,
        "evaluated_total": evaluated_total,
        "correct_total": correct_total,
        "accuracy_pct": accuracy_pct,
        "pending_pct": pending_pct,
    })

    try:
        return render_template("main/analytics_accuracy.html", **context)
    except Exception as e:
        current_app.logger.error(f"Error rendering accuracy analytics page: {e}")
        return "Something went wrong loading accuracy analytics.", 500


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
            filtered, camera_options, meta = _query_activities(db)
            total_count = len(filtered)

            start_idx = (page - 1) * per_page
            page_items = filtered[start_idx:start_idx + per_page]

            for doc in page_items:
                doc["_id"] = str(doc["_id"])
                doc["timestamp_display"] = _format_timestamp(doc.get("timestamp"))

            activities = page_items
        except Exception as e:
            current_app.logger.error(f"Error fetching activities for history page: {e}")
            error = "Could not load activity history."

    total_pages = max((total_count + per_page - 1) // per_page, 1)

    context = _base_context()
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
        filtered, _, _ = _query_activities(db)
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
    doc["timestamp_display"] = _format_timestamp(doc.get("timestamp"))

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

    context = _base_context()
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


@main_bp.route("/media/<path:filepath>")
def serve_media(filepath):
    """Serve evidence images stored under UPLOAD_FOLDER."""
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filepath)


@main_bp.route("/audio/<path:filename>")
def serve_audio(filename):
    """
    Serve Live Monitoring signal sound files with a long cache lifetime
    (audio files rarely change, unlike CSS/JS which are still actively
    developed) - so after the first play, the browser never re-fetches
    them, keeping playback instant.
    """
    audio_dir = os.path.join(current_app.root_path, "static", "audio")
    return send_from_directory(audio_dir, filename, max_age=604800)  # 7 days
