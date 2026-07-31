"""
app/main/routes.py
-------------------
General pages and static-asset serving: Home, health check, Settings,
evidence images, and audio files.

Feature-specific routes live in sibling modules - see app/main/__init__.py.
"""

import os

from flask import (
    current_app, flash, redirect, render_template, request,
    send_from_directory, url_for,
)

from app.main import main_bp
from app.main.shared import base_context


@main_bp.route("/")
def home():
    """Home page - kept empty/minimal for now, content lives on other pages."""
    try:
        return render_template("main/home.html", **base_context())
    except Exception as e:
        current_app.logger.error(f"Error rendering home page: {e}")
        return "Something went wrong loading the home page.", 500


@main_bp.route("/health")
def health():
    """Health check endpoint for CI/CD and uptime monitoring."""
    return "OK", 200


@main_bp.route("/settings", methods=["GET", "POST"])
def settings():
    """Settings - currently controls the Live Monitoring signal behaviour
    (blink/solid pattern, duration, whether color is retained after a blink)."""
    from app.settings_store import get_live_signal_settings, save_live_signal_settings

    db = current_app.extensions.get("mongo_db")

    if request.method == "POST":
        pattern = request.form.get("pattern", "blink")
        if pattern not in ("blink", "solid"):
            pattern = "blink"

        try:
            duration_sec = float(request.form.get("duration_sec", 5))
        except (TypeError, ValueError):
            duration_sec = 5
        duration_sec = max(1, min(duration_sec, 60))  # sane bounds: 1-60 sec

        retain_color = request.form.get("retain_color") == "on"

        if save_live_signal_settings(db, pattern, duration_sec, retain_color):
            flash("Settings saved.", "success")
        else:
            flash("Could not save settings - database unavailable.", "error")

        return redirect(url_for("main.settings"))

    try:
        context = base_context()
        context["live_signal_settings"] = get_live_signal_settings(db)
        return render_template("main/settings.html", **context)
    except Exception as e:
        current_app.logger.error(f"Error rendering settings page: {e}")
        return "Something went wrong loading settings.", 500


@main_bp.route("/media/<path:filepath>")
def serve_media(filepath):
    """Serve evidence images stored under UPLOAD_FOLDER."""
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filepath)


@main_bp.route("/audio/<path:filename>")
def serve_audio(filename):
    """
    Serve Live Monitoring signal sound files with a long cache lifetime
    (audio files rarely change, unlike CSS/JS which are still actively
    developed) - so after the first play, the browser never re-fetches
    them, keeping playback instant.
    """
    audio_dir = os.path.join(current_app.root_path, "static", "audio")
    return send_from_directory(audio_dir, filename, max_age=604800)  # 7 days
