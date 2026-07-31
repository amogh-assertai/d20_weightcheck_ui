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
from app.extensions import init_mongo, init_socketio


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Centralized logging setup (console always, rotating file when not in debug)
    setup_logger(app)

    # Set up shared extensions (MongoDB, SocketIO)
    init_mongo(app)
    init_socketio(app)

    # Import the socket event handlers so the @socketio.on(...) decorator in
    # app/sockets.py actually registers (nothing else calls this module -
    # pure side-effect-on-import, same pattern as blueprints).
    # NOTE: must use "from app import sockets", NOT "import app.sockets" -
    # the latter would rebind the local `app` variable (this function's Flask
    # instance) to the `app` package itself, breaking everything below it.
    from app import sockets  # noqa: F401

    # --- Register blueprints ---
    # app.main's __init__ creates the blueprint and imports every route
    # module in the package, so all routes are attached by this point.
    from app.main import main_bp
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
