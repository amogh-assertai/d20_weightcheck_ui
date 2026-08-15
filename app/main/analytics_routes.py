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

# Known result types get this display order first (matches the existing
# PASS/FAIL/MISSING_DATA convention); anything else found in the data is
# appended afterwards, most-frequent first - so a brand new result type
# (e.g. NOT_IMPLEMENTED) just works, with no code change required.
KNOWN_RESULT_ORDER = ["PASS", "FAIL", "MISSING_DATA"]


def _build_result_type_order(result_counts):
    """Canonical display order used for stat cards, legend, and every
    per-camera breakdown - same order everywhere on the page."""
    known = [r for r in KNOWN_RESULT_ORDER if r in result_counts]
    other = sorted(
        (r for r in result_counts if r not in KNOWN_RESULT_ORDER),
        key=lambda r: result_counts[r],
        reverse=True,
    )
    return known + other


@main_bp.route("/analytics")
def analytics():
    """Analytics section landing - redirects to the first sub-page (System Analytics)."""
    return redirect(url_for("main.analytics_system"))


@main_bp.route("/analytics/system")
def analytics_system():
    """
    System Analytics: activity volume, camera-wise distribution, and top-5
    highest weight differences - all scoped to a date range (defaults to
    today only).

    Result-type breakdown (stat cards, legend, per-camera bars/lines) is
    fully dynamic: every distinct validation_result value actually present
    in the data gets its own tracked count, at every level (global total,
    per-camera). This is deliberate - an earlier version only tracked
    PASS/FAIL/MISSING_DATA by name and lumped everything else into an
    "other" bucket that was drawn on the graph but never added into any
    displayed number, so totals didn't add up once a new result type
    appeared. Missing/null validation_result is treated as its own
    "UNKNOWN" bucket for the same reason - it must be counted somewhere,
    not silently dropped.
    """
    db = current_app.extensions.get("mongo_db")
    error = None
    total_count = 0
    camera_distribution = []
    top_weight_diff = []
    result_types = []
    result_counts = {}
    result_pcts = {}

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

            # Per-camera breakdown: total + a count per distinct result type
            # actually seen for that camera - not a fixed set of buckets.
            camera_stats = {}
            for doc in filtered:
                cam = doc.get("camera_name", "Unknown")
                result = doc.get("validation_result") or "UNKNOWN"

                result_counts[result] = result_counts.get(result, 0) + 1

                cstats = camera_stats.setdefault(cam, {"total": 0, "results": {}})
                cstats["total"] += 1
                cstats["results"][result] = cstats["results"].get(result, 0) + 1

            camera_distribution = sorted(
                camera_stats.items(), key=lambda kv: kv[1]["total"], reverse=True
            )
            result_types = _build_result_type_order(result_counts)

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

    result_pcts = {
        r: (round(result_counts[r] / total_count * 100, 1) if total_count else 0.0)
        for r in result_types
    }

    context = base_context()
    context.update({
        "error": error,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "total_count": total_count,
        "result_types": result_types,
        "result_counts": result_counts,
        "result_pcts": result_pcts,
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
    review of FAIL/MISSING_DATA activities (the error_type field), NOT a
    fixed number. See the calculation breakdown rendered directly on the
    page - the formula and every intermediate count are shown, not just the
    final percentage, since this changes as review progresses.

    error_type is a single consolidated field (SYSTEM_ERROR / PROCESS_ERROR
    / BOTH / ALL_OK / untouched) - it replaced two separate mark_ocr_wrong /
    mark_process_error fields that could disagree with each other (e.g.
    both marked Yes had no defined meaning, needing an inferred tiebreak).
    That ambiguity is gone now: BOTH is an explicit value, not a guess.

    Rules (also explained on the page itself):
    - PASS is always counted as correct.
    - FAIL/MISSING_DATA is only included if error_type has been set at all -
      if it's still untouched, it's excluded (pending review).
    - error_type == SYSTEM_ERROR or BOTH -> incorrect.
      error_type == PROCESS_ERROR or ALL_OK -> correct.

    Note: this page intentionally still treats anything outside PASS/FAIL/
    MISSING_DATA as "not part of the accuracy calculation" (skipped, not
    counted anywhere) - unlike System Analytics, which now tracks every
    result type. A new result type showing up here needs its own accuracy
    rule defined explicitly (is it correct-by-default like PASS, or does it
    need review like FAIL/MISSING_DATA?) - that's a business decision, not
    something safe to infer automatically the way a display count is.
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

                error_type = doc.get("error_type")

                if error_type is None:
                    unmarked_non_pass += 1
                else:
                    reviewed_non_pass += 1
                    if error_type in ("SYSTEM_ERROR", "BOTH"):
                        system_error_count += 1
                    else:  # PROCESS_ERROR or ALL_OK
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