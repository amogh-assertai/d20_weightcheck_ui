# CV Data Console

Flask-based cloud UI + data-management layer. Local CV/AI clients push data
and real-time signals to this app; this app has no AI/CV logic itself.

## Folder structure

```
cv_webapp/
├── app/
│   ├── __init__.py        # App factory - creates app, loads config, registers blueprints
│   ├── config.py          # ALL app behaviour settings live here (+ .env)
│   ├── main/               # Blueprint: home page / general UI
│   │   ├── __init__.py
│   │   └── routes.py
│   ├── static/
│   │   ├── css/style.css
│   │   ├── js/             # (empty for now)
│   │   └── img/            # (empty for now)
│   ├── templates/
│   │   ├── base.html
│   │   └── main/home.html
│   └── utils/
│       ├── helpers.py     # generic stateless helper functions
│       └── logger.py      # centralized logging setup
├── instance/               # untracked, per-deployment data (uploads, etc.)
├── .env                    # local secrets/config - NOT committed
├── .env.example            # template for .env - safe to commit
├── requirements.txt
└── run.py                  # entry point
```

## Running locally

```bash
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # if not already present
python run.py
```

Visit http://localhost:5000

## Changing behaviour without touching code

Edit `.env` (or `app/config.py` for structural defaults):
- `APP_NAME`, `MAX_CLIENTS`, `HOST`, `PORT`, `MAX_CONTENT_LENGTH_MB`, `SECRET_KEY`

## Planned next additions (not built yet - by design, kept out until needed)

- `app/api/` blueprint - REST endpoints for local clients to POST data
- `app/events/` (or socket handlers) - WebSocket layer for real-time sync across all clients
- Storage decision (DB vs flat files vs cloud object storage) - pending your input on data type/volume
