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
│   ├── settings_store.py      # Live Monitoring signal settings, in MongoDB
│   ├── audio_config.py        # Loads app/audio_config.json
│   ├── audio_config.json      # EDIT THIS to change sounds per table/result
│   │
│   ├── main/                  # Blueprint: all UI pages, split by feature
│   │   ├── __init__.py            # creates main_bp, imports the route modules
│   │   ├── shared.py              # template context, parsing, sort key, filter query
│   │   ├── routes.py              # home, health, settings, media/audio serving
│   │   ├── live_routes.py         # Live Monitoring board + details lookup
│   │   ├── history_routes.py      # History table, Activity Details, review saving
│   │   └── analytics_routes.py    # Analytics (System + Accuracy)
│   │
│   ├── api/                   # Blueprint: endpoints the AI device calls
│   │   ├── __init__.py
│   │   └── routes.py              # POST /activities, POST /webhook/activity-result
│   │
│   ├── static/
│   │   ├── css/                   # one base sheet + one per page area
│   │   │   ├── base.css               # theme, chrome, layout, badges, flash, fit-to-screen
│   │   │   ├── forms.css              # filter bars, form controls, pagination
│   │   │   ├── history.css            # results table + Flags column
│   │   │   ├── activity_detail.css    # detail layout, zoom viewer, review panel
│   │   │   ├── analytics.css          # stat cards, camera bars, accuracy flowchart
│   │   │   ├── errors.css             # 404 / 500 / details-pending
│   │   │   └── live_monitoring.css    # the board, signal states, audio UI
│   │   ├── js/
│   │   │   ├── main.js                # theme toggle, flash dismiss, toggle buttons
│   │   │   ├── live_monitoring.js     # socket updates, signal, audio
│   │   │   ├── activity_detail.js     # image zoom/pan, arrow-key navigation
│   │   │   └── socket.io.min.js       # self-hosted client (do NOT use a CDN - see below)
│   │   └── audio/                 # your .mp3 files (names must match audio_config.json)
│   │
│   ├── templates/
│   │   ├── base.html              # shared layout + flash messages
│   │   ├── _macros.html           # shared Jinja macros (result -> colour class)
│   │   ├── errors/404.html, 500.html
│   │   └── main/
│   │       ├── home.html, settings.html
│   │       ├── live_monitoring.html       # + #live-monitoring-config JSON block
│   │       ├── history.html
│   │       ├── activity_detail.html
│   │       ├── live_details_pending.html
│   │       ├── analytics_system.html
│   │       └── analytics_accuracy.html
│   └── utils/
│       ├── helpers.py         # generic helpers + timestamp formatters (24h and 12h)
│       └── logger.py          # centralized logging setup
│
├── tests/                     # pytest regression suite (240 tests)
│   ├── conftest.py                # fixtures: app, client, socket client, sample data
│   ├── test_pages.py              # every route renders, shared chrome present
│   ├── test_api_ingestion.py      # POST /api/activities
│   ├── test_api_webhook.py        # webhook validation, dedup, socket broadcast
│   ├── test_history.py            # filters, search, sort, pagination, flags
│   ├── test_activity_detail.py    # detail page, prev/next, review save logic
│   ├── test_analytics.py          # system totals + every accuracy rule
│   ├── test_live_monitoring.py    # board, settings-driven signal, audio, lookup
│   ├── test_static_assets.py      # CSS/JS wiring after the asset split
│   ├── test_macros.py             # shared Jinja macros
│   └── test_infrastructure.py     # error pages, helpers, multi-worker consistency
│
├── instance/uploads/          # untracked, evidence images land here
├── .env / .env.example
├── .gitignore
├── pytest.ini
├── requirements.txt           # production
├── requirements-dev.txt       # pytest + mongomock (test only)
└── run.py                     # entry point (eventlet + SocketIO)
```

### Why it's split this way

- **Route modules by feature.** `main/routes.py` had grown to 765 lines
  covering six unrelated areas. Each module is now one feature; the blueprint
  itself is created in `main/__init__.py` so every module can import it
  without a circular import (the standard Flask pattern for splitting one
  blueprint across files).
- **One base stylesheet + one per page area.** `style.css` had reached 1309
  lines, all of it loaded on every page. `base.css` and `forms.css` load
  globally; each page pulls only its own sheet via the `extra_head` block.
- **No inline JavaScript.** The Live Monitoring script was 210 lines inside
  the template, so the browser re-downloaded it on every page load and it
  couldn't be linted. It now lives in `static/js/live_monitoring.js`, with
  the four server-supplied values passed through a
  `#live-monitoring-config` JSON block instead of being templated in.
- **Shared macros for colour mapping.** The `result -> colour class` ternary
  was inlined six times across three templates. Note `badge_class()` and
  `pass_fail_class()` are deliberately different (`MISSING_DATA` -> orange
  vs `MISSING` -> grey) and must not be merged - there's a test guarding it.

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

## Testing

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

240 tests, no external services needed - `mongomock` provides an in-memory
MongoDB, and Flask-SocketIO's test client covers the WebSocket path.

What's covered: every page rendering, both AI-device endpoints (including
webhook duplicate suppression and socket broadcast), all History
filters/search/sort/pagination, Activity Details prev/next and the
`result_reviewed` logic, every Accuracy calculation rule (including the
both-marked-Yes edge case), settings-driven signal behaviour, audio config
wiring, static-asset wiring, error pages, and the multi-worker consistency
guarantee.

Several tests exist specifically to guard against regressions that already
happened once - each is commented with what it's protecting. Notably:
webhook duplicates must not re-trigger signals; live status must be read
from MongoDB (not per-process memory); the Socket.IO client must be
self-hosted; retained colour must survive a page refresh without replaying
the blink; and audio must only fire on a live socket update, never on
render.

One `EventletDeprecationWarning` appears at import time and is expected -
eventlet is still the supported async worker for Flask-SocketIO. It's
raised during collection, before pytest's warning filters engage, so it
can't be filtered cleanly; it's cosmetic.

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
