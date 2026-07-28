"""
app/live_status.py
-------------------
Latest-result-per-table logic, backed by MongoDB (collection:
live_latest_data, one document per table, upserted - always exactly 4
documents).

Split into two steps on purpose (rather than one combined "record" call):

  1. check_is_duplicate() - a read, used to decide whether this webhook call
     is genuinely new or an exact repeat.
  2. persist_result() - the actual MongoDB write.

This lets the webhook route (app/api/routes.py) broadcast the update to
browser clients via WebSocket BEFORE writing to MongoDB - the client update
is the time-critical part (blink/audio sync to the real event), while the
MongoDB write is bookkeeping that can happen immediately after without
blocking that.

Reads always go straight to MongoDB (no in-memory cache) - an earlier
version cached in-process, which broke under multiple Gunicorn workers
(each has its own separate memory, so one worker's webhook update wouldn't
be visible to another worker's requests). MongoDB is the one place every
worker actually shares.
"""

VALID_TABLE_IDS = ("table_1", "table_2", "table_3", "table_4")
REQUIRED_FIELDS = ("result", "activity_number", "activity_datetime", "order_number")


def check_is_duplicate(db, table_id, result, activity_number):
    """True if this exact (table_id, result, activity_number) is already the latest stored value."""
    if db is None:
        return False
    try:
        existing = db["live_latest_data"].find_one({"table_id": table_id})
    except Exception:
        return False
    return (
        existing is not None
        and existing.get("activity_number") == activity_number
        and existing.get("result") == result
    )


def persist_result(db, table_id, data):
    """Upsert the given data (already includes received_at) into MongoDB for one table."""
    if db is None:
        return
    try:
        db["live_latest_data"].update_one(
            {"table_id": table_id},
            {"$set": {"table_id": table_id, **data}},
            upsert=True,
        )
    except Exception:
        pass  # a Mongo hiccup shouldn't crash the webhook response


def get_latest_status(db):
    """
    Current latest-data snapshot for all 4 tables, read directly from
    MongoDB - used for the Live Monitoring page's initial server-rendered
    state (WebSocket handles everything after page load).
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
        pass
    return status
