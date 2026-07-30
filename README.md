# Weight Check

Flask-based cloud UI + data-management layer for **Watts-Water-D20**.

Local AI/detection machines (camera stations, one per packing table) run the
actual weight/order verification pipeline and send data to this app two ways:
a full historical record (metadata + evidence image) via REST, and a
lightweight real-time signal via webhook for the Live Monitoring board. This
app has no AI/CV logic itself — it receives, stores, displays, and lets a
human review that data.

## Folder structure

```
cv_webapp/
├── app/
│   ├── __init__.py            # App factory - Mongo, SocketIO, blueprints, error handlers
│   ├── config.py              # ALL app behaviour settings (+ .env)
│   ├── extensions.py          # MongoDB client + SocketIO instance setup
│   ├── sockets.py             # WebSocket push: backend -> browser (Live Monitoring only)
│   ├── live_status.py         # Latest-per-table data (reads/writes MongoDB directly)
│   ├── settings_store.py      # Live Monitoring signal settings (blink/solid/duration/retain), in MongoDB
│   ├── audio_config.py        # Loads app/audio_config.json
│   ├── audio_config.json      # EDIT THIS to change which sound plays for which table/result
│   ├── main/                  # Blueprint: all UI pages
│   │   └── routes.py          # Home, Live Monitoring, Settings, History, Activity Details,
│   │                          # Analytics (System + Accuracy), media/audio serving
│   ├── api/                   # Blueprint: endpoints the AI device calls
│   │   └── routes.py          # POST /activities (full record), POST /webhook/activity-result (live signal)
│   ├── static/
│   │   ├── css/
│   │   │   ├── style.css          # Everything except Live Monitoring
│   │   │   └── live_monitoring.css # Live Monitoring page only (big cards, signal states, audio UI)
│   │   ├── js/
│   │   │   ├── main.js            # Theme toggle, flash-message auto-dismiss, toggle-button feedback
│   │   │   └── socket.io.min.js    # Self-hosted client (do NOT load this from a CDN - see note below)
│   │   └── audio/              # Put your .mp3 files here (names must match audio_config.json)
│   ├── templates/
│   │   ├── base.html               # Shared layout: top bar + nav + theme toggle + flash messages
│   │   ├── errors/404.html, 500.html
│   │   └── main/
│   │       ├── home.html                  # Placeholder for now
│   │       ├── live_monitoring.html       # Real-time board (4 table cards)
│   │       ├── settings.html              # Live Monitoring signal controls
│   │       ├── history.html               # Filterable/searchable/sortable/paginated activity log
│   │       ├── activity_detail.html       # Prev/next, zoomable image, review form
│   │       ├── live_details_pending.html  # "Not uploaded yet, try again" page
│   │       ├── analytics_system.html      # Analytics > System Analytics
│   │       └── analytics_accuracy.html    # Analytics > Accuracy (flowchart)
│   └── utils/
│       ├── helpers.py         # Generic helpers + shared timestamp formatters
│       └── logger.py          # Centralized logging setup
├── instance/uploads/          # Untracked, evidence images land here
├── .env / .env.example
├── .gitignore
├── requirements.txt
└── run.py                     # Entry point (eventlet + SocketIO)
```

**Cleanup note:** `app/templates/main/analytics.html` is a leftover placeholder
from an earlier iteration and is no longer referenced by any route (`/analytics`
redirects straight to `/analytics/system` now) — safe to delete.

## Running locally

```bash
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # adjust values, especially MONGO_URI
python run.py
```

Visit http://localhost:5000. Requires a running MongoDB instance.

## Configuration (.env)

| Variable | Purpose |
|---|---|
| `APP_NAME` | Internal app name (Home page heading) |
| `CLIENT_NAME` | Displayed client/site name (top bar, browser tab, footer) |
| `SECRET_KEY` | Flask secret key — change for real deployments |
| `FLASK_DEBUG` | `True`/`False` — **must be `False`** for the custom error pages to show (see Error handling below) |
| `HOST`, `PORT` | Bind address |
| `MAX_CLIENTS` | Informational only |
| `MAX_CONTENT_LENGTH_MB` | Upload size limit |
| `MONGO_URI`, `MONGO_DB_NAME` | This app's own MongoDB connection |
| `LIVE_DETAILS_TYPE` | `new_tab` (default) or `current_tab` — where Live Monitoring's "View Details" opens |

Live Monitoring's signal **pattern/duration/retain-color** are configured live
via the Settings page (stored in MongoDB), not `.env` — that's intentional, so
they can be changed without redeploying.

## Pages & features

- **Home** — placeholder, kept empty for now
- **Live Monitoring** — the real-time shop-floor board:
  - 4 corner cards, one per table (layout: table 3 top-left, table 1
    top-right, table 4 bottom-left, table 2 bottom-right)
  - Each card shows Activity Number, RESULT, Order #, and Datetime (12-hour,
    AM/PM)
  - Updates arrive via **WebSocket** the instant the AI's webhook fires — no
    polling, minimal latency (deliberately chosen over polling once audio/blink
    needed to sync closely to the actual detection moment)
  - **Signal**: card blinks or goes solid (configurable in Settings — pattern,
    duration in seconds, and whether the color is retained until the next
    update). The retained color is computed server-side on page load too, so
    a refresh shows the correct state without replaying the blink/audio
  - **Audio**: plays a configured sound per table+result combination (see
    `app/audio_config.json`), preloaded on page load for instant playback,
    the configured number of times back-to-back. Missing/broken audio files
    fail silently (logged quietly, never breaks the page). A corner badge
    shows audio on/off; if blocked by the browser's autoplay policy, a
    full-page "click anywhere to enable audio" modal appears — any click,
    tap, or keypress anywhere on the page unlocks it
  - **View Details** button looks up the matching full record in
    `all_activities` by activity_number + order_number (restricted to
    today's date); if the AI's separate upload hasn't landed yet, shows a
    "try again shortly" page that auto-retries after 5 seconds
  - Page uses a fit-to-screen layout (no page-level scrolling)
- **Settings** — controls the Live Monitoring signal: Blink or Solid pattern,
  duration (1–60s), and whether color is retained until the next update
  (applies to both patterns)
- **History** — filter by table / date range (default today) / result
  (including `MISSING_DATA`) / marked-for-discussion / system-error /
  comment (present/absent), search by order # or activity #, sortable
  columns, pagination (25/50/100/page). A **Flags** column shows compact
  badges (D/E/P/C) for discuss/system-error/process-error/comment — shown
  for both Yes and No (not just Yes), blank only if genuinely untouched.
  Setting the Comment filter to "Present" switches to a reduced column set
  with a wide, wrapped (not truncated) comment column.
- **Activity Details** — prev/next navigation through whatever filtered set
  you came from, zoomable/pannable evidence image (scroll to zoom, drag to
  pan), order/weight fields on one side and activity/reasoning on the other,
  and a review form: **Marked for discussion**, **System error**, **Process
  error** (all Yes/No), plus a free-text comment. Saving flashes a
  confirmation toast. Page is fit-to-screen (no scrolling).
- **Analytics → System Analytics** — date-range-filtered totals, per-camera
  breakdown (stacked bar showing PASS/FAIL/MISSING_DATA composition, with
  exact counts and percentages per camera), Top 5 highest **absolute**
  weight-difference activities (not percentage) with links back to their
  detail pages.
- **Analytics → Accuracy** — a **dynamic** metric that depends on ongoing
  human review, presented as an HTML/CSS flowchart:
  `Total → PASS (always correct) / FAIL+MISSING_DATA → Reviewed / Not
  Reviewed (excluded) → System Error (incorrect) / Process Error or
  confirmed (correct) → Total Correct → formula with real numbers
  substituted in`. Defaults to yesterday's date. Explicitly documents the
  edge case where an activity is marked Yes for both System Error and
  Process Error (System Error takes priority).

## Ingestion & real-time — two separate channels from the AI device

**1. `POST /api/activities`** — full historical record (multipart/form-data):
- `activity_data` — JSON string (camera_id, camera_name, activity_number,
  validation_result, order/weight fields, etc. — flexible, extra fields
  stored as-is)
- `image` — the evidence image file

Saves the image to `instance/uploads/{date}/{camera_id}__{camera_name}/`
(date from the activity's own `timestamp`), stores the path in the document,
inserts into MongoDB **`all_activities`** — the one source of truth for
history/Analytics.

**2. `POST /api/webhook/activity-result`** — lightweight, fire-and-forget,
drives the Live Monitoring board only:
```json
{"table_id": "table_1", "result": "PASS", "activity_number": 42,
 "activity_datetime": "2026-07-28T10:15:00+00:00", "order_number": "E0857781"}
```
- `table_id` must be one of `table_1`..`table_4`
- On receipt: if this exact (table_id, result, activity_number) was already
  the latest stored value, it's silently ignored (`"status":
  "duplicate_ignored"`) — this stops a looping/retrying sender from causing
  endless re-blinks/re-plays
- If genuinely new: **broadcasts to all connected browsers via WebSocket
  first**, then persists to MongoDB **`live_latest_data`** (one document per
  table, upserted) — broadcast-before-persist is deliberate, since the
  client update is the time-critical part
- No auth on either endpoint currently (open by explicit choice)

## Real-time (WebSocket)

Uses **Flask-SocketIO + eventlet**. The AI device does **not** connect to
this socket at all — it only ever calls the two HTTP endpoints above. The
socket exists purely to push `table_update` events to browsers with the
Live Monitoring page open.

**Reads for the live board always go straight to MongoDB, not an in-memory
cache** — an earlier version cached in-process, which broke under multiple
Gunicorn workers (each has separate memory, so one worker's webhook update
was invisible to another worker's requests, causing data to appear to
randomly "revert"). Fixed by making MongoDB the single shared source of
truth for every read.

### Deployment requirement

Gunicorn must run with a single eventlet worker, not the default sync
workers:
```
ExecStart=/path/to/venv/bin/gunicorn -k eventlet -w 1 -b 0.0.0.0:PORT run:app
```
One worker is required because Socket.IO's connected-client state lives in
that process; multiple workers would each have a separate, inconsistent
view. A single eventlet worker still handles many concurrent connections
cooperatively — it is not the same as single-threaded blocking.

`run.py` calls `eventlet.monkey_patch()` before any other import — required
for eventlet's async mode to work correctly; must stay the first lines in
that file.

## Audio system

`app/audio_config.json` is the single file to edit — no code changes needed:
```json
"table_1": {
  "PASS": {"file": "table1_pass.mp3", "times": 1},
  "FAIL": {"file": "table1_fail.mp3", "times": 1},
  "MISSING_DATA": {"file": "table1_missing.mp3", "times": 1}
}
```
Drop the matching `.mp3` files in `app/static/audio/`. Served via a
dedicated `/audio/<file>` route with a 7-day browser cache (scoped only to
audio — CSS/JS keep normal caching since they're still actively developed).
Audio only ever plays on a genuine live WebSocket update, never on page
load/refresh (same principle as the blink/color signal).

## Data model — three MongoDB collections

- **`all_activities`** — full historical record, one document per
  finalized activity, written by `POST /api/activities`. Mirrors the AI
  backend's own schema, plus review fields this app adds: `mark_discuss`,
  `mark_ocr_wrong` ("System error" in the UI), `mark_process_error`,
  `review_comment`, `result_reviewed` (true if any of the first three has
  been touched, including an explicit "No").
- **`live_latest_data`** — one document per table (upserted), latest data
  only, written by the webhook. Purely for the live board.
- **`app_settings`** — one document (`_id: "live_signal_settings"`)
  holding the Live Monitoring signal pattern/duration/retain-color,
  editable via the Settings page.

## Error handling

Custom branded 404/500 pages with a **Refresh** button — but these **only
render when `FLASK_DEBUG=False`**. With `debug=True` (local dev), Flask's
own interactive debugger takes over instead, which is intentional so you
keep full tracebacks while developing. Make sure your real deployment sets
`FLASK_DEBUG=False` to get the custom pages instead of a raw/blank error.

## Known scaling notes

- History and Analytics fetch matching documents into Python and
  filter/sort/aggregate there, rather than via a MongoDB aggregation
  pipeline — because `timestamp` is stored as a string, not a native Mongo
  date. Fine at current volumes; worth revisiting (proper aggregation +
  native date field) if a single deployment's history grows very large.
- Evidence images are served through Flask itself with no caching headers
  currently (the `/media/` route) — audio already got this treatment
  (`/audio/`, 7-day cache); doing the same for `/media/` is a cheap,
  queued-up improvement, along with eventually letting Nginx serve that
  path directly instead of routing through a Gunicorn worker.

## Planned / not yet built

- Settings page currently only controls the Live Monitoring signal — no
  other app-behaviour settings live there yet
- Ingestion/webhook endpoint authentication (currently open, by explicit
  choice)
- `/media/` (evidence image) caching headers (see above)
