"""
app/sockets.py
--------------
WebSocket push channel: Flask backend -> browser (Live Monitoring) clients
ONLY. Separate from the AI device's channel, which is plain HTTP webhooks
(see app/api/routes.py) - the AI device never connects to this socket at all.

Purpose: the instant the webhook receives genuinely new data, broadcast it
to every browser currently viewing Live Monitoring, so the card update +
blink (and future audio) happen as close to real-time as possible - no
polling delay.
"""

from app.extensions import socketio
from app.utils.helpers import format_timestamp


def broadcast_table_update(table_id, data):
    """Push one table's new data to every connected browser client immediately."""
    payload = dict(data)
    payload["activity_datetime_display"] = format_timestamp(data.get("activity_datetime"))
    socketio.emit("table_update", {"table_id": table_id, **payload})


@socketio.on("connect")
def handle_connect(auth=None):
    # Browsers just connect to receive broadcasts - nothing to authenticate
    # or track per-connection for this channel.
    pass
