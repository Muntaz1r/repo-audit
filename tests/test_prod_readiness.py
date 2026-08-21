import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.services.analyzers.prod_readiness import ProdReadinessAnalyzer
from app.database import SessionLocal
from app.models import Audit, AuditPillar, AuditFinding

@pytest.mark.asyncio
async def test_prod_readiness_complete_repo(tmp_path: Path):
    # Setup CI/CD
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "test.yml").write_text("name: Test\non: [push]")
    
    # Setup Docker
    (tmp_path / "Dockerfile").write_text("FROM python:3.11-slim\nCMD ['python']")
    (tmp_path / "docker-compose.yml").write_text("services:\n  app:\n    build: .")
    
    # Setup Hygiene
    (tmp_path / ".gitignore").write_text("__pycache__/\n*.pyc")
    (tmp_path / "package-lock.json").write_text('{"name": "app", "lockfileVersion": 3}')
    (tmp_path / "app.py").write_text("import logging\nlogging.info('Ready')")

    analyzer = ProdReadinessAnalyzer()
    result = await analyzer.analyze(tmp_path, {"owner": "test", "repo_name": "ready-repo", "primary_language": "Python"})

    assert result.pillar_key == "prod_readiness"
    assert result.score >= 90
    assert result.status == "PASS"
    assert result.metrics_json["has_ci_cd"] is True
    assert result.metrics_json["has_containerization"] is True
    assert result.metrics_json["has_gitignore"] is True
    assert result.metrics_json["has_structured_logging"] is True
    assert len(result.findings) == 0

@pytest.mark.asyncio
async def test_prod_readiness_missing_infrastructure(tmp_path: Path):
    (tmp_path / "main.py").write_text("print('no docker, no ci')")

    analyzer = ProdReadinessAnalyzer()
    result = await analyzer.analyze(tmp_path, {"owner": "test", "repo_name": "bare-repo", "primary_language": "Python"})

    assert result.pillar_key == "prod_readiness"
    assert result.score < 60
    assert result.status in ["WARN", "FAIL"]
    assert result.metrics_json["has_ci_cd"] is False
    assert result.metrics_json["has_containerization"] is False
    assert result.metrics_json["has_gitignore"] is False
    assert len(result.findings) >= 3

def test_export_audit_endpoint():
    db = SessionLocal()
    audit_id = "aud_test_export_unique"
    try:
        existing = db.query(Audit).filter(Audit.id == audit_id).first()
        if existing:
            db.delete(existing)
            db.commit()

        audit = Audit(
            id=audit_id,
            repo_url="https://github.com/test/repo",
            owner="test",
            repo_name="repo",
            status="COMPLETED",
            overall_score=88,
            overall_grade="B",
            verdict_summary="High quality codebase."
        )
        db.add(audit)
        db.commit()

        client = TestClient(app)
        
        # Test Markdown Export
        resp_md = client.get(f"/api/audits/{audit_id}/export?format=markdown")
        assert resp_md.status_code == 200
        assert "RepoAudit Report" in resp_md.text
        assert "attachment" in resp_md.headers.get("content-disposition", "")

        # Test JSON Export
        resp_json = client.get(f"/api/audits/{audit_id}/export?format=json")
        assert resp_json.status_code == 200
        data = resp_json.json()
        assert data["audit_id"] == audit_id
        assert data["overall_score"] == 88
    finally:
        db.close()
