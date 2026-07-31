"""
app/main/__init__.py
---------------------
Creates the `main` blueprint, then imports the route modules so their
@main_bp.route(...) decorators register.

The blueprint is defined here (before those imports) so every route module
can do `from app.main import main_bp` without a circular import - the
standard Flask pattern for splitting one blueprint across several files.

Routes are grouped by feature:
  routes.py            - home, health, settings, media/audio serving
  live_routes.py       - Live Monitoring board + its details lookup
  history_routes.py    - History table, Activity Details, review saving
  analytics_routes.py  - Analytics (System + Accuracy)
"""

from flask import Blueprint

main_bp = Blueprint("main", __name__, template_folder="../templates/main")

# Imported for side effects only (route registration) - keep at the bottom.
from app.main import routes            # noqa: E402,F401
from app.main import live_routes       # noqa: E402,F401
from app.main import history_routes    # noqa: E402,F401
from app.main import analytics_routes  # noqa: E402,F401
