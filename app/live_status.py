"""
app/live_status.py
-------------------
Latest-result-per-table lookup, backed directly by MongoDB (collection:
live_latest_data, one document per table, upserted - always exactly 4
documents).

IMPORTANT: reads go straight to MongoDB on every call, NOT an in-memory
cache. An earlier version kept an in-memory cache for speed, but that
broke under multiple Gunicorn worker processes - each worker has its own
separate memory, so a webhook landing on worker A only updated worker A's
copy, while a page load/poll landing on worker B kept showing whatever
worker B last happened to see (stale, and inconsistent between requests
depending on which worker handled them - looks like data "reverting" to
an older value). MongoDB is the one place every worker actually shares,
so reading from it directly is what's correct here.
"""

from datetime import datetime, timezone

VALID_TABLE_IDS = ("table_1", "table_2", "table_3", "table_4")
REQUIRED_FIELDS = ("result", "activity_number", "activity_datetime", "order_number")


def record_result(db, table_id, result, activity_number, activity_datetime, order_number):
    """
    Upsert the latest data for one table into MongoDB - but ONLY if this is
    genuinely new (different activity_number or different result than what's
    already stored). An exact repeat is silently ignored and received_at is
    left untouched. Returns True if recorded, False if skipped as a duplicate.

    This matters because received_at is what the frontend polling compares
    to decide "something changed, blink the card." If a sender re-POSTs the
    same activity repeatedly (loop, retry logic, etc.), the old behavior
    treated every single POST as new and kept re-triggering the blink
    indefinitely. Now: one genuinely new activity -> one signal to the UI.
    """
    if db is None:
        return False

    try:
        existing = db["live_latest_data"].find_one({"table_id": table_id})
    except Exception:
        existing = None

    is_duplicate = (
        existing is not None
        and existing.get("activity_number") == activity_number
        and existing.get("result") == result
    )
    if is_duplicate:
        return False

    data = {
        "result": result,
        "activity_number": activity_number,
        "activity_datetime": activity_datetime,
        "order_number": order_number,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        db["live_latest_data"].update_one(
            {"table_id": table_id},
            {"$set": {"table_id": table_id, **data}},
            upsert=True,
        )
    except Exception:
        pass  # a Mongo hiccup shouldn't crash the webhook response
    return True


def get_latest_status(db):
    """
    Current latest-data snapshot for all 4 tables, read directly from
    MongoDB every call - not cached - so every Gunicorn worker process
    sees exactly the same data.
    """
    status = {table_id: None for table_id in VALID_TABLE_IDS}
    if db is None:
        return status
    try:
        for doc in db["live_latest_data"].find({"table_id": {"$in": list(VALID_TABLE_IDS)}}):
            table_id = doc.get("table_id")
            if table_id in VALID_TABLE_IDS:
                status[table_id] = {
                    "result": doc.get("result"),
                    "activity_number": doc.get("activity_number"),
                    "activity_datetime": doc.get("activity_datetime"),
                    "order_number": doc.get("order_number"),
                    "received_at": doc.get("received_at"),
                }
    except Exception:
        pass  # best-effort - returns whatever tables were readable, None for the rest
    return status
