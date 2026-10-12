import pytest
from app import app
from src.db import init_db

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

def test_dashboard_routes(client):
    """Ensures all 4 dashboard pages and download routes return HTTP 200 OK without calling AI."""
    # Overview page
    resp_overview = client.get("/")
    assert resp_overview.status_code == 200
    assert b"MoveInSync" in resp_overview.data

    # Issues page
    resp_issues = client.get("/issues")
    assert resp_issues.status_code == 200
    assert b"Ranked Problem Diagnostics" in resp_issues.data

    # Explorer page
    resp_explorer = client.get("/explorer")
    assert resp_explorer.status_code == 200
    assert b"Review Explorer" in resp_explorer.data

    # Health page
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert b"Pipeline Health" in resp_health.data

    # Jira CSV download
    resp_csv = client.get("/download/action_items_csv")
    assert resp_csv.status_code == 200
    assert b"Issue Key" in resp_csv.data
