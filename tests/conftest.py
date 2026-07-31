"""
tests/conftest.py
------------------
Shared pytest fixtures for the regression suite.

Uses mongomock (an in-memory fake MongoDB) so tests run anywhere with no
real database. Production still uses real pymongo/MongoDB - mongomock is a
test-only dependency.

Run the suite with:  pytest
"""

import os
import sys
from datetime import datetime, timezone, timedelta

import mongomock
import pytest

# Make the project root importable regardless of where pytest is invoked from
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402
from app.extensions import socketio  # noqa: E402


class TestConfig(Config):
    """Test config - isolated upload folder, debug off so error handlers run."""
    TESTING = True
    DEBUG = False
    UPLOAD_FOLDER = "/tmp/weightcheck_test_uploads"
    LIVE_DETAILS_TYPE = "new_tab"


@pytest.fixture
def db():
    """A fresh in-memory MongoDB for each test."""
    return mongomock.MongoClient().db


@pytest.fixture
def app(db):
    """Flask app wired to the in-memory database."""
    application = create_app(TestConfig)
    application.extensions["mongo_db"] = db
    return application


@pytest.fixture
def client(app):
    """Standard Flask test client (HTTP requests)."""
    return app.test_client()


@pytest.fixture
def socket_client(app, client):
    """Flask-SocketIO test client - needed to assert WebSocket broadcasts."""
    return socketio.test_client(app, flask_test_client=client)


@pytest.fixture
def today():
    return datetime.now(timezone.utc).date()


@pytest.fixture
def yesterday():
    return datetime.now(timezone.utc).date() - timedelta(days=1)


def make_activity(
    activity_number=1,
    camera_name="camera_4",
    camera_id=0,
    validation_result="PASS",
    date=None,
    hour=10,
    order_number="E0001",
    expected_weight="10.0",
    actual_weight="10.0",
    weight_difference="0.0",
    weight_difference_percent="0.0%",
    order_number_matching="YES",
    **extra,
):
    """
    Build an `all_activities`-shaped document. Mirrors the real schema from
    the AI backend (string-typed weights included, deliberately).
    """
    if date is None:
        date = datetime.now(timezone.utc).date()
    doc = {
        "camera_id": camera_id,
        "camera_name": camera_name,
        "activity_number": activity_number,
        "mode": "MONITORING",
        "expected_order_number": order_number,
        "actual_order_number": order_number,
        "order_number_matching": order_number_matching,
        "order_number_result": "PASS",
        "expected_weight": expected_weight,
        "actual_weight": actual_weight,
        "weight_difference": weight_difference,
        "weight_difference_percent": weight_difference_percent,
        "weight_result": validation_result,
        "validation_result": validation_result,
        "validation_reason": "test reason",
        "timestamp": f"{date.isoformat()}T{hour:02d}:00:00+00:00",
    }
    doc.update(extra)
    return doc


@pytest.fixture
def insert_activity(db):
    """Insert an activity document and return its string _id."""
    def _insert(**kwargs):
        doc = make_activity(**kwargs)
        return str(db["all_activities"].insert_one(doc).inserted_id)
    return _insert


@pytest.fixture
def webhook_payload(today):
    """A valid payload for POST /api/webhook/activity-result."""
    def _payload(
        table_id="table_1",
        result="PASS",
        activity_number=1,
        order_number="E0001",
        date=None,
        hour=10,
    ):
        d = date or today
        return {
            "table_id": table_id,
            "result": result,
            "activity_number": activity_number,
            "activity_datetime": f"{d.isoformat()}T{hour:02d}:15:00+00:00",
            "order_number": order_number,
        }
    return _payload
