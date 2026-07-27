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
from flask import Flask, render_template, current_app
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

    # --- Error pages ---
    # Note: these only render when FLASK_DEBUG=False. With debug=True (local dev),
    # Flask's own interactive debugger takes over instead - that's expected, since
    # you want full tracebacks while developing. In a real deployment (debug=False),
    # an unhandled error shows this branded page with a Refresh button instead of a
    # blank/raw error.
    def _error_context():
        return {
            "app_name": current_app.config.get("APP_NAME", ""),
            "client_name": current_app.config.get("CLIENT_NAME", ""),
            "max_clients": current_app.config.get("MAX_CLIENTS", ""),
        }

    @app.errorhandler(404)
    def handle_404(e):
        return render_template("errors/404.html", **_error_context()), 404

    @app.errorhandler(500)
    def handle_500(e):
        current_app.logger.error(f"Internal server error: {e}")
        return render_template("errors/500.html", **_error_context()), 500

    # Make sure the upload folder exists. Don't crash the app if it can't be created -
    # just log a warning so the developer notices during setup.
    try:
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    except OSError as e:
        app.logger.warning(f"Could not create upload folder '{app.config['UPLOAD_FOLDER']}': {e}")

    app.logger.info(f"{app.config['APP_NAME']} initialized successfully.")
    return app
