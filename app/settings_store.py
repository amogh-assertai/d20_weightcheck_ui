"""
app/settings_store.py
----------------------
App-wide, user-configurable behaviour settings - currently just the Live
Monitoring signal pattern (blink vs solid, duration, whether color is
retained). Stored in MongoDB (collection: app_settings, one document) so
they're changeable live from the Settings page without touching code or
redeploying, and persist across restarts.
"""

DEFAULT_LIVE_SIGNAL_SETTINGS = {
    "pattern": "blink",      # "blink" or "solid"
    "duration_sec": 5,
    "retain_color": False,   # applies to both patterns - keeps the color after the signal ends
}

_SETTINGS_ID = "live_signal_settings"


def get_live_signal_settings(db):
    """Current live-signal settings, falling back to defaults if unset/unreachable."""
    if db is None:
        return dict(DEFAULT_LIVE_SIGNAL_SETTINGS)
    try:
        doc = db["app_settings"].find_one({"_id": _SETTINGS_ID})
    except Exception:
        doc = None
    if not doc:
        return dict(DEFAULT_LIVE_SIGNAL_SETTINGS)
    return {
        "pattern": doc.get("pattern", DEFAULT_LIVE_SIGNAL_SETTINGS["pattern"]),
        "duration_sec": doc.get("duration_sec", DEFAULT_LIVE_SIGNAL_SETTINGS["duration_sec"]),
        "retain_color": doc.get("retain_color", DEFAULT_LIVE_SIGNAL_SETTINGS["retain_color"]),
    }


def save_live_signal_settings(db, pattern, duration_sec, retain_color):
    """Persist the live-signal settings. Caller should validate inputs first. Returns True on success."""
    if db is None:
        return False
    try:
        db["app_settings"].update_one(
            {"_id": _SETTINGS_ID},
            {"$set": {
                "pattern": pattern,
                "duration_sec": duration_sec,
                "retain_color": retain_color,
            }},
            upsert=True,
        )
        return True
    except Exception:
        return False
