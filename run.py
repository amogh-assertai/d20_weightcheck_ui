"""
run.py
------
Entry point to start the Flask app.
Run with: python run.py
(or `flask run` if FLASK_APP=run.py is set - see .env.example)

IMPORTANT: eventlet.monkey_patch() MUST run before anything else is imported
(including create_app / pymongo) - Flask-SocketIO's eventlet async mode needs
the stdlib's socket/threading modules patched before other libraries grab
references to the unpatched versions. Importing create_app first would be
too late and cause subtle, hard-to-debug connection issues.
"""

import eventlet
eventlet.monkey_patch()

from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    # host/port are controlled via config.py / .env - no code change needed to adjust them.
    # socketio.run() (not app.run()) is required so WebSocket connections work correctly.
    socketio.run(app, host=app.config["HOST"], port=app.config["PORT"], debug=app.config["DEBUG"])
