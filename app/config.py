"""
config.py
---------
Single source of truth for application behaviour.
Change values here or via .env - avoid hardcoding behaviour-tweaks in route/logic files.
"""

import os
from dotenv import load_dotenv

# Load variables from a .env file (if present) into the environment
load_dotenv()

# Absolute path to project root (one level above /app)
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


class Config:
    """Base configuration. Values can be overridden via environment variables (.env file)."""

    # --- General ---
    APP_NAME = os.environ.get("APP_NAME", "Weight Check")
    CLIENT_NAME = os.environ.get("CLIENT_NAME", "Watts-Water-D20")
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")  # ASSUMPTION: replace in real deployment
    DEBUG = os.environ.get("FLASK_DEBUG", "True") == "True"

    # --- Server ---
    HOST = os.environ.get("HOST", "0.0.0.0")
    PORT = int(os.environ.get("PORT", 5000))

    # --- Client scale (informational / used for future validation, NOT enforced yet) ---
    # Expected max local CV clients connecting to this console.
    MAX_CLIENTS = int(os.environ.get("MAX_CLIENTS", 100))

    # --- Upload / data handling (used once the data-ingestion blueprint is added) ---
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH_MB", 50)) * 1024 * 1024  # bytes
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "instance", "uploads")

    # --- Data storage (MongoDB) ---
    # This is OUR cloud-side database - separate from the local machine's own MongoDB.
    # Local AI clients upload activity metadata + image here; we store our own copy.
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "d20_cloud")
