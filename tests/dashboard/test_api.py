from fastapi.testclient import TestClient

from dashboard.backend.app import app


def test_health():
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
