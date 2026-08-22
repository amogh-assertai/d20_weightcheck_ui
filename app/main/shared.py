"""
app/main/shared.py
-------------------
Helpers shared by the route modules in this package: template context,
activity-data parsing, and the one filter/search/sort query used by both
the History page and Activity Details' prev/next navigation.

Lives here (rather than app/utils/) because everything in this file is
specific to the activity-data domain and these page routes - app/utils/
holds genuinely generic helpers.
"""

from datetime import datetime, timezone

from flask import current_app, request


def base_context():
    """Shared template variables used by every page in this blueprint."""
    return {
        "app_name": current_app.config["APP_NAME"],
        "client_name": current_app.config["CLIENT_NAME"],
        "max_clients": current_app.config["MAX_CLIENTS"],
    }


def parse_activity_date(timestamp_value):
    """Parse an activity's ISO timestamp string into just its date, or None if unparseable."""
    if not timestamp_value:
        return None
    try:
        return datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_numeric(value):
    """Parse a numeric string, optionally with a trailing '%' (e.g. '24.23%' or '9.800'), into a float. Returns None if not parseable."""
    if value is None:
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except ValueError:
        return None


def sort_key(doc, field):
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


def query_activities(db):
    """
    Shared filter/search/sort logic used by both the History page and the
    Activity Detail page's prev/next navigation, so both always agree on
    "what's in the current filtered set" and in what order.
    Reads all filter/search/sort values from request.args.
    """
    table_filter = request.args.get("table", "all")
    result_filter = request.args.get("result", "all")
    search_term = request.args.get("search", "").strip()
    error_type_filter = request.args.get("error_type", "all")  # "all" / SYSTEM_ERROR / PROCESS_ERROR / BOTH / ALL_OK
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
    result_options = []
    filtered = []

    if db is not None:
        camera_options = sorted(db["all_activities"].distinct("camera_name"))
        # Same pattern as camera_options: whatever result values actually
        # exist in the data become selectable filter options - a new result
        # type (e.g. NOT_IMPLEMENTED) is filterable immediately, with no
        # code change. Falsy/missing values are dropped (an empty option in
        # a dropdown isn't a meaningful filter choice).
        result_options = sorted(v for v in db["all_activities"].distinct("validation_result") if v)

        # Mongo-side filter: built as a list of independent conditions,
        # combined with $and only if there's more than one. A flat dict
        # would break if two conditions both need their own $or clause
        # (e.g. NOT_YET_REVIEWED and has_comment=absent both do) - the
        # second assignment would silently overwrite the first.
        conditions = []
        if table_filter != "all":
            conditions.append({"camera_name": table_filter})
        if result_filter != "all":
            conditions.append({"validation_result": result_filter})

        if error_type_filter == "NOT_YET_REVIEWED":
            # Not a real stored value - "not yet reviewed" means BOTH: no
            # error_type classification (none of SYSTEM_ERROR/PROCESS_ERROR/
            # BOTH/ALL_OK) AND no comment either. An activity with a
            # comment but no error_type yet is partially reviewed, not
            # untouched - it must not match this filter.
            conditions.append({"$and": [
                {"$or": [
                    {"error_type": {"$exists": False}},
                    {"error_type": None},
                ]},
                {"$or": [
                    {"review_comment": {"$exists": False}},
                    {"review_comment": None},
                    {"review_comment": ""},
                ]},
            ]})
        elif error_type_filter != "all":
            conditions.append({"error_type": error_type_filter})

        if discuss_filter in ("YES", "NO"):
            conditions.append({"mark_discuss": discuss_filter})
        if has_comment_filter == "present":
            conditions.append({"review_comment": {"$exists": True, "$nin": ["", None]}})
        elif has_comment_filter == "absent":
            conditions.append({"$or": [
                {"review_comment": {"$exists": False}},
                {"review_comment": ""},
                {"review_comment": None},
            ]})

        if len(conditions) > 1:
            mongo_query = {"$and": conditions}
        elif conditions:
            mongo_query = conditions[0]
        else:
            mongo_query = {}

        all_matching = list(db["all_activities"].find(mongo_query))

        # Date range + text search applied in Python - timestamps are stored as
        # ISO strings (not native Mongo dates), so parsing here is more robust
        # than a string-range Mongo query.
        for doc in all_matching:
            doc_date = parse_activity_date(doc.get("timestamp"))
            if doc_date is not None and not (start_date <= doc_date <= end_date):
                continue

            if search_term:
                haystack = " ".join(str(doc.get(f, "")) for f in
                                     ["expected_order_number", "actual_order_number", "activity_number"])
                if search_term.lower() not in haystack.lower():
                    continue

            filtered.append(doc)

        filtered.sort(key=lambda d: sort_key(d, sort_field), reverse=(sort_order == "desc"))

    meta = {
        "selected_table": table_filter,
        "selected_result": result_filter,
        "search_term": search_term,
        "selected_error_type": error_type_filter,
        "selected_has_comment": has_comment_filter,
        "selected_discuss": discuss_filter,
        "selected_sort": sort_field,
        "selected_order": sort_order,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "result_options": result_options,
    }
    return filtered, camera_options, meta
