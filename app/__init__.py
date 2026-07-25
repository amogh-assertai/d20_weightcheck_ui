"""
app/__init__.py
----------------
Application factory. Keeps app creation modular:
- loads config
- sets up logging
- registers blueprints
New blueprints (e.g. REST ingestion API, WebSocket events) get registered here later
without touching any other file.
"""

import os
from flask import Flask
from app.config import Config
from app.utils.logger import setup_logger
from app.extensions import init_mongo


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Centralized logging setup (console always, rotating file when not in debug)
    setup_logger(app)

    # Set up shared extensions (currently just MongoDB)
    init_mongo(app)

    # --- Register blueprints ---
    from app.main.routes import main_bp
    app.register_blueprint(main_bp)

    from app.api.routes import api_bp
    app.register_blueprint(api_bp, url_prefix="/api")

    # Make sure the upload folder exists. Don't crash the app if it can't be created -
    # just log a warning so the developer notices during setup.
    try:
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    except OSError as e:
        app.logger.warning(f"Could not create upload folder '{app.config['UPLOAD_FOLDER']}': {e}")

    app.logger.info(f"{app.config['APP_NAME']} initialized successfully.")
    return app
