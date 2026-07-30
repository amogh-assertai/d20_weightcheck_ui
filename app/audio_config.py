"""
app/audio_config.py
--------------------
Loads the table+result -> audio file/play-count mapping from a single JSON
config file (app/audio_config.json) - editable directly, no code changes
needed to change which sound plays, for which table/result, or how many
times.
"""

import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "audio_config.json")


def load_audio_config():
    """
    Returns the full mapping, e.g.:
    {"table_1": {"PASS": {"file": "table1_pass.mp3", "times": 1}, ...}, ...}
    Falls back to an empty dict (no audio configured) if the file is
    missing or malformed, so a bad config file doesn't break the page.
    """
    try:
        with open(_CONFIG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
