import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db

init_db()
client = TestClient(app)

def test_api_health_and_index():
    response = client.get("/")
    assert response.status_code == 200

def test_create_audit_invalid_url():
    response = client.post("/api/audits", json={"repo_url": "invalid-url"})
    assert response.status_code == 400
    assert "Invalid GitHub URL" in response.json()["detail"]

def test_create_audit_valid_url():
    response = client.post("/api/audits", json={"repo_url": "https://github.com/expressjs/express"})
    assert response.status_code == 202
    data = response.json()
    assert "id" in data
    assert data["status"] in ["QUEUED", "CLONING", "ANALYZING", "COMPLETED"]
    assert data["owner"] == "expressjs"
    assert data["repo_name"] == "express"

    audit_id = data["id"]
    get_res = client.get(f"/api/audits/{audit_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == audit_id
