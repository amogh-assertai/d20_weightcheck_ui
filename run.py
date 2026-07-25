"""
run.py
------
Entry point to start the Flask app.
Run with: python run.py
(or `flask run` if FLASK_APP=run.py is set - see .env.example)
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    # host/port are controlled via config.py / .env - no code change needed to adjust them
    app.run(host=app.config["HOST"], port=app.config["PORT"], debug=app.config["DEBUG"])
