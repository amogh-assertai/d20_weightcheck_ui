"""
extensions.py
-------------
Shared clients/extensions used across the app. Currently just MongoDB.
Kept separate from app/__init__.py so connection details don't clutter
the application factory, and so other extensions can be added here later
without touching factory logic.
"""

from pymongo import MongoClient
from pymongo.errors import PyMongoError


def init_mongo(app):
    """
    Create the MongoDB client and attach the database handle to app.extensions,
    so blueprints can access it via current_app.extensions['mongo_db'].

    Note: pymongo connects lazily - this won't raise just because MongoDB isn't
    reachable yet. Actual connection problems surface when a query/insert runs,
    which the ingestion routes handle per-request (so one bad request doesn't
    crash the whole app).
    """
    try:
        client = MongoClient(app.config["MONGO_URI"], serverSelectionTimeoutMS=5000)
        db = client[app.config["MONGO_DB_NAME"]]
        app.extensions["mongo_db"] = db
        app.logger.info(f"MongoDB configured: db='{app.config['MONGO_DB_NAME']}'")
    except PyMongoError as e:
        # Don't crash app startup - ingestion routes will report a clean 503
        # if they try to use the DB and it's genuinely unreachable.
        app.logger.error(f"Could not configure MongoDB client: {e}")
        app.extensions["mongo_db"] = None
    return app.extensions.get("mongo_db")
