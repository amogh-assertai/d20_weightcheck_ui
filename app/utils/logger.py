"""
utils/logger.py
----------------
Centralized logging configuration for the whole app.
Console logging always on; rotating file logging kicks in when DEBUG is off
(i.e. real/cloud deployment) so logs don't grow unbounded.
"""

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(app):
    """Attach console + (optionally) rotating file handlers to the Flask app logger."""
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    # Keep the ROOT logger at INFO regardless of app debug mode.
    # Reason: basicConfig(level=DEBUG) applies to every library's logger too
    # (e.g. 'watchdog', used by Flask's reloader), which floods the console
    # with file-watch events from unrelated packages like site-packages/onnx.
    logging.basicConfig(level=logging.INFO, format=log_format)

    # Only OUR app's logger gets DEBUG verbosity when app.config["DEBUG"] is True.
    app.logger.setLevel(logging.DEBUG if app.config["DEBUG"] else logging.INFO)

    # Explicitly silence known-noisy third-party loggers used by the dev reloader.
    logging.getLogger("watchdog").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.INFO)

    if not app.config["DEBUG"]:
        try:
            log_dir = os.path.join(app.root_path, "..", "logs")
            os.makedirs(log_dir, exist_ok=True)

            file_handler = RotatingFileHandler(
                os.path.join(log_dir, "app.log"),
                maxBytes=1_000_000,  # ~1MB per file
                backupCount=3,       # keep last 3 rotated files
            )
            file_handler.setFormatter(logging.Formatter(log_format))
            file_handler.setLevel(logging.INFO)
            app.logger.addHandler(file_handler)
        except OSError as e:
            # Don't let logging setup crash the app - fall back to console-only
            app.logger.warning(f"Could not set up file logging: {e}")

    app.logger.info(f"Logging initialized. Debug mode: {app.config['DEBUG']}")
