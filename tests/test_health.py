from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_app_and_database():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "ok"
    assert body["database"]["connected"] is True
    assert body["database"]["vector_extension"] is True
