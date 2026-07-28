"""
app/live_status.py
-------------------
Latest-result-per-table store. Written by the AI device's webhook
(POST /api/webhook/activity-result, see app/api/routes.py), read by:
  - the Live Monitoring page on initial load (server-rendered)
  - GET /live-status, polled by the browser every few seconds for
    near-real-time updates (see live_monitoring.html)

Backed by MongoDB (collection: live_latest_data, one document per table,
upserted - so there are always exactly 4 documents) so the "latest" view
survives a server restart. An in-memory cache sits on top so repeated
polls from multiple browser tabs don't all hit MongoDB - load_from_db()
repopulates that cache from MongoDB once at app startup.
"""

from datetime import datetime, timezone

VALID_TABLE_IDS = ("table_1", "table_2", "table_3", "table_4")
REQUIRED_FIELDS = ("result", "activity_number", "activity_datetime", "order_number")

_latest_by_table = {table_id: None for table_id in VALID_TABLE_IDS}


def _doc_to_dict(doc):
    return {
        "result": doc.get("result"),
        "activity_number": doc.get("activity_number"),
        "activity_datetime": doc.get("activity_datetime"),
        "order_number": doc.get("order_number"),
        "received_at": doc.get("received_at"),
    }


def load_from_db(db):
    """
    Populate the in-memory cache from MongoDB - call once at app startup,
    so a restart doesn't lose the 'latest' view for tables that still have
    valid recent data. Best-effort: if this fails, webhook/polling still
    work fine going forward, just start from an empty cache.
    """
    if db is None:
        return
    try:
        for doc in db["live_latest_data"].find({}):
            table_id = doc.get("table_id")
            if table_id in VALID_TABLE_IDS:
                _latest_by_table[table_id] = _doc_to_dict(doc)
    except Exception:
        pass


def record_result(db, table_id, result, activity_number, activity_datetime, order_number):
    """
    Store the latest data for one table - upserts into MongoDB and updates
    the in-memory cache. Caller must validate table_id/required fields first.
    """
    data = {
        "result": result,
        "activity_number": activity_number,
        "activity_datetime": activity_datetime,
        "order_number": order_number,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    if db is not None:
        try:
            db["live_latest_data"].update_one(
                {"table_id": table_id},
                {"$set": {"table_id": table_id, **data}},
                upsert=True,
            )
        except Exception:
            # Don't let a Mongo hiccup break the live-display update itself -
            # the in-memory cache below still gets updated regardless.
            pass

    _latest_by_table[table_id] = data


def get_latest_status():
    """
    Current latest-data snapshot for all 4 tables - a fresh copy each call,
    safe for callers to add their own display-only fields to (e.g. a
    formatted datetime) without mutating the shared in-memory cache.
    """
    return {
        table_id: (dict(data) if data else None)
        for table_id, data in _latest_by_table.items()
    }
