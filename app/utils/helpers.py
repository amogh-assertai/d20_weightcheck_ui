"""
utils/helpers.py
-----------------
Small, generic helper functions used across blueprints.
Keep this file for lightweight, stateless utilities only - anything that grows
complex (e.g. file/image handling) should get pulled into its own module later.
"""

from datetime import datetime, timezone


def utc_now_iso() -> str:
    """
    Return the current UTC time in ISO 8601 format.
    Useful for consistent timestamps when clients report events/data.
    """
    return datetime.now(timezone.utc).isoformat()


def is_allowed_file(filename: str, allowed_extensions: set) -> bool:
    """
    Generic filename/extension validator.
    Example: is_allowed_file("photo.jpg", {"jpg", "png"}) -> True
    """
    if not filename or "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in allowed_extensions


def format_timestamp(timestamp_value) -> str:
    """
    Human-readable timestamp for display, e.g. '24 Jul 2026, 22:28:48'.
    Shared so the History/Activity Detail pages, Live Monitoring's initial
    render, AND the WebSocket broadcast payload all format dates identically.
    """
    if not timestamp_value:
        return "-"
    try:
        dt = datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %H:%M:%S")
    except ValueError:
        return str(timestamp_value)


def format_timestamp_12h(timestamp_value) -> str:
    """
    Human-readable timestamp with a 12-hour clock + AM/PM, e.g.
    '28 Jul 2026, 02:30:05 PM'. Used specifically for the Live Monitoring
    cards (explicit request for 12-hour format there) - other pages keep
    the 24-hour format_timestamp() above.
    """
    if not timestamp_value:
        return "-"
    try:
        dt = datetime.fromisoformat(str(timestamp_value).replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %I:%M:%S %p")
    except ValueError:
        return str(timestamp_value)
