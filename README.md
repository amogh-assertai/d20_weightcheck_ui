# Weight Check

Flask-based cloud UI + data-management layer for **Watts-Water-D20**.

Local AI/detection machines (camera stations) run the actual weight/order
verification pipeline and push activity metadata + evidence images to this
app over HTTP. This app has no AI/CV logic itself — it receives, stores,
displays, and lets a human review that data.

## Folder structure

```
cv_webapp/
├── app/
│   ├── __init__.py            # App factory - loads config, sets up MongoDB, registers blueprints
│   ├── config.py              # ALL app behaviour settings live here (+ .env)
│   ├── extensions.py          # MongoDB client setup
│   ├── main/                  # Blueprint: all UI pages
│   │   ├── __init__.py
│   │   └── routes.py          # Home, Live Monitoring, Settings, History, Activity Details,
│   │                          # review-save endpoint, evidence-image serving, Analytics
│   ├── api/                   # Blueprint: REST ingestion from local clients
│   │   ├── __init__.py
│   │   └── routes.py          # POST /api/activities (metadata + image upload)
│   ├── static/
│   │   ├── css/style.css      # Single stylesheet, dark/light theme via CSS variables
│   │   ├── js/main.js         # Theme toggle (persists choice in localStorage)
│   │   └── img/               # (empty for now)
│   ├── templates/
│   │   ├── base.html          # Shared layout: top bar + nav + theme toggle
│   │   └── main/
│   │       ├── home.html              # Placeholder for now
│   │       ├── live_monitoring.html   # Board with 4 table cards (Table 1-4)
│   │       ├── settings.html          # Placeholder for now
│   │       ├── history.html           # Filterable/searchable/sortable/paginated activity log
│   │       ├── activity_detail.html   # Prev/next, zoomable image, review form
│   │       └── analytics_system.html  # System Analytics (first Analytics sub-page)
│   └── utils/
│       ├── helpers.py         # Generic stateless helper functions
│       └── logger.py          # Centralized logging setup
├── instance/                  # Untracked, per-deployment local data (uploads/, etc.)
├── .env                       # Local secrets/config - NOT committed
├── .env.example                # Template for .env - safe to commit
├── .gitignore
├── requirements.txt
└── run.py                     # Entry point
```

## Running locally

```bash
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # adjust values, especially MONGO_URI
python run.py
```

Visit http://localhost:5000

Requires a running MongoDB instance (`MONGO_URI` in `.env`) — this app's
database is separate from any MongoDB running on the local detection
machines themselves.

## Configuration (.env)

All behaviour is controlled via `.env` — no code changes needed for these:

| Variable | Purpose |
|---|---|
| `APP_NAME` | Internal app name (shown on the Home page heading) |
| `CLIENT_NAME` | Displayed client/site name (top bar, browser tab, footer) |
| `SECRET_KEY` | Flask secret key - change for real deployments |
| `FLASK_DEBUG` | `True`/`False` |
| `HOST`, `PORT` | Bind address for `run.py` |
| `MAX_CLIENTS` | Informational - expected max local clients |
| `MAX_CONTENT_LENGTH_MB` | Upload size limit |
| `MONGO_URI`, `MONGO_DB_NAME` | This app's own MongoDB connection |

## Pages

- **Home** — placeholder, kept empty for now
- **Live Monitoring** — board with 4 corner cards (Table 1-4); real-time
  signal wiring (color changes, audio) not built yet
- **Settings** — placeholder
- **History** — filter by table/date range/result/marked-for-discussion/
  system-error/comment, search by order # or activity #, sortable columns,
  pagination (25/50/100 per page)
- **Activity Details** — prev/next navigation through the filtered set,
  zoomable/pannable evidence image, order/weight fields (left) and activity/
  reasoning fields (right), review form (mark for discussion, mark system
  error, free-text comment)
- **Analytics → System Analytics** — date-range-filtered totals (PASS/FAIL/
  MISSING_DATA), per-camera breakdown with stacked bars, top 5 highest
  weight-difference activities. Built as a section so more analytics
  sub-pages can be added later.

## Ingestion API

**`POST /api/activities`** — `multipart/form-data`:
- `activity_data` — JSON string matching the activity schema (camera_id,
  camera_name, activity_number, validation_result, etc. — flexible, extra
  fields stored as-is)
- `image` — the evidence image file

Saves the image to `instance/uploads/{date}/{camera_id}__{camera_name}/`
(date taken from the activity's own `timestamp` field), stores the resulting
path in the document, and inserts the whole thing into the `all_activities`
MongoDB collection.

No auth is currently enforced on this endpoint - it's assumed to sit behind
network-level access control (e.g. only reachable from known client IPs).

## Data model

Documents in `all_activities` mirror the local detection backend's own
schema (camera_id, camera_name, activity_number, expected/actual order
number and weight, validation_result, image_path, timestamp, etc.), plus
review fields added by this app:

- `mark_discuss` — `"YES"` / `"NO"` / unset (untouched)
- `mark_ocr_wrong` — `"YES"` / `"NO"` / unset (untouched) — shown in the UI as "System error"
- `review_comment` — free text
- `result_reviewed` — `True` if any of the above three has been touched, `False` if all three are still untouched

## Deployment

Runs under **Gunicorn** (not Uvicorn — Flask is WSGI, not ASGI) as a
systemd service for 24/7 uptime with auto-restart on failure. See prior
setup notes for the exact service file; adjust paths/venv location as
needed per environment.

## Known scaling note

History and Analytics currently fetch matching documents into Python and
filter/sort/aggregate there (rather than via a MongoDB aggregation
pipeline), since `timestamp` is stored as a string rather than a native
Mongo date. Fine at current data volumes - worth revisiting (proper
aggregation pipeline + native date field) if a single deployment's activity
history grows very large.

## Planned / not yet built

- Real-time signal wiring on Live Monitoring (color changes, audio alerts)
  based on live detection results
- Settings page content
- Additional Analytics sub-pages
- Ingestion endpoint authentication (currently open, by explicit choice)
