"""
app/main/analytics_routes.py
----------------------------
Analytics section: System Analytics (volume, per-camera breakdown, top
weight differences) and Accuracy (the review-dependent dynamic metric).
"""

from datetime import datetime, timedelta, timezone

from flask import current_app, redirect, render_template, request, url_for

from app.main import main_bp
from app.main.shared import base_context, parse_activity_date, parse_numeric


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
                doc_date = parse_activity_date(doc.get("timestamp"))
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
                diff = parse_numeric(doc.get("weight_difference"))
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

    context = base_context()
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
                if parse_activity_date(doc.get("timestamp")) != selected_date:
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

    context = base_context()
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
