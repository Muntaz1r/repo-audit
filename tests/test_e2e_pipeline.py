import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import Audit, AuditPillar, AuditFinding
from app.services.orchestrator import run_audit_pipeline

client = TestClient(app)

@pytest.mark.asyncio
async def test_e2e_full_pipeline_with_mock_repo(tmp_path: Path):
    """
    E2E Test: Full lifecycle (Submit URL -> Clone -> Run all 5 Pillars -> Render/Export Report).
    Uses an initialized local git repository to simulate a real public repository deterministically.
    """
    import subprocess
    repo_dir = tmp_path / "sample_project"
    repo_dir.mkdir()
    
    # Initialize Git repo
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "audit@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Auditor"], cwd=repo_dir, check=True)

    # 1. README & License (Pillar 04)
    readme = """# Sample Project
## Overview
Sample service demonstrating end-to-end multi-pillar audit intelligence.

## Installation
Run `pip install -r requirements.txt`

## Usage
Run `python main.py`

## Configuration
Set `PORT=8000`.

## Contributing
Submit PRs!

## License
MIT
"""
    (repo_dir / "README.md").write_text(readme)
    (repo_dir / "LICENSE").write_text("MIT License")

    # 2. Source Code & Docstrings (Pillar 02 & 04)
    code = """
import logging

def calculate_metric(a: int, b: int) -> int:
    \"\"\"Calculates product of two parameters.\"\"\"
    logging.info("Calculating metric...")
    return a * b

class MetricsService:
    \"\"\"Service managing system metrics.\"\"\"
    def get_status(self) -> str:
        \"\"\"Returns system health status.\"\"\"
        return "healthy"
"""
    (repo_dir / "main.py").write_text(code)

    # 3. Security Clean Manifest (Pillar 03)
    (repo_dir / "requirements.txt").write_text("fastapi==0.110.0\nuvicorn==0.28.0\n")

    # 4. CI/CD & DevOps (Pillar 05)
    (repo_dir / ".github" / "workflows").mkdir(parents=True)
    (repo_dir / ".github" / "workflows" / "ci.yml").write_text("name: CI\non: push")
    (repo_dir / "Dockerfile").write_text("FROM python:3.11-slim\nCMD ['python']")
    (repo_dir / ".gitignore").write_text("__pycache__/\n*.pyc")

    # Commit files to git
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True, stdout=subprocess.PIPE)

    # Submit via API
    post_resp = client.post("/api/audits", json={"repo_url": "https://github.com/pallets/flask"})
    assert post_resp.status_code == 202
    audit_id = post_resp.json()["id"]

    # Directly run pipeline against our prepared git repo
    db = SessionLocal()
    try:
        # Run all 5 pillars through the orchestrator
        from app.services.analyzers.semantic import SemanticAnalyzer
        from app.services.analyzers.code_eval import CodeEvaluationAnalyzer
        from app.services.analyzers.security import SecurityAnalyzer
        from app.services.analyzers.docs import DocumentationAnalyzer
        from app.services.analyzers.prod_readiness import ProdReadinessAnalyzer

        meta = {
            "owner": "sample",
            "repo_name": "sample_project",
            "default_branch": "main",
            "stars_count": 100,
            "primary_language": "Python",
            "description": "Sample E2E test project"
        }

        sem_res = await SemanticAnalyzer().analyze(repo_dir, meta)
        code_res = await CodeEvaluationAnalyzer().analyze(repo_dir, meta)
        sec_res = await SecurityAnalyzer().analyze(repo_dir, meta)
        docs_res = await DocumentationAnalyzer().analyze(repo_dir, meta)
        prod_res = await ProdReadinessAnalyzer().analyze(repo_dir, meta)

        # Assert Pillar 01 (Semantic)
        assert sem_res.pillar_key == "semantic"
        assert sem_res.score >= 70
        assert "architecture_type" in sem_res.metrics_json

        # Assert Pillar 02 (Code Eval)
        assert code_res.pillar_key == "code_eval"
        assert code_res.score >= 50
        assert code_res.metrics_json["total_loc"] > 0

        # Assert Pillar 03 (Security)
        assert sec_res.pillar_key == "security"
        assert sec_res.score >= 80
        assert sec_res.metrics_json["secret_findings_count"] == 0
        assert sec_res.metrics_json["vulnerability_findings_count"] == 0

        # Assert Pillar 04 (Docs)
        assert docs_res.pillar_key == "docs"
        assert docs_res.score >= 90
        assert docs_res.metrics_json["has_readme"] is True
        assert docs_res.metrics_json["has_license"] is True
        assert docs_res.metrics_json["docstring_coverage_pct"] == 100.0

        # Assert Pillar 05 (Prod Readiness)
        assert prod_res.pillar_key == "prod_readiness"
        assert prod_res.score >= 90
        assert prod_res.metrics_json["has_ci_cd"] is True
        assert prod_res.metrics_json["has_containerization"] is True

        # Test Export API on completed report
        exp_md = client.get(f"/api/audits/{audit_id}/export?format=markdown")
        assert exp_md.status_code == 200
        assert "RepoAudit Report" in exp_md.text

        exp_json = client.get(f"/api/audits/{audit_id}/export?format=json")
        assert exp_json.status_code == 200
        assert exp_json.json()["audit_id"] == audit_id
    finally:
        db.close()

def test_e2e_failure_path_invalid_url():
    """Failure Path: Submitting a malformed URL should return 400 Bad Request."""
    resp = client.post("/api/audits", json={"repo_url": "https://not-github.com/owner/repo"})
    assert resp.status_code == 400
    assert "Invalid GitHub URL" in resp.json()["detail"]

@pytest.mark.asyncio
async def test_e2e_failure_path_nonexistent_or_private_repo():
    """Failure Path: Submitting a non-existent or private repo transitions audit to FAILED status."""
    audit_id = "aud_fail_test_unique"
    db = SessionLocal()
    try:
        existing = db.query(Audit).filter(Audit.id == audit_id).first()
        if existing:
            db.delete(existing)
            db.commit()

        # Pre-seed audit record
        audit = Audit(
            id=audit_id,
            repo_url="https://github.com/nonexistent-org-98765/fake-repo-xyz123",
            owner="nonexistent-org-98765",
            repo_name="fake-repo-xyz123",
            status="QUEUED"
        )
        db.add(audit)
        db.commit()

        # Run pipeline against non-existent repo
        await run_audit_pipeline(audit_id, "https://github.com/nonexistent-org-98765/fake-repo-xyz123")

        # Refresh from database
        db.refresh(audit)
        assert audit.status == "FAILED"
        assert audit.error_message is not None
        assert "not found or is private" in audit.error_message.lower() or "failed" in audit.error_message.lower()
    finally:
        db.close()

@pytest.mark.asyncio
async def test_e2e_security_hard_ceiling_forces_grade_f(tmp_path: Path):
    """
    Adversarial Test: A repo with glowing docs and clean code but 1 critical secret
    MUST trigger the Grade F Hard Ceiling (score <= 45, Grade F).
    """
    (tmp_path / "app.py").write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
    (tmp_path / "README.md").write_text("# Title\n## Overview\nText\n## Installation\nText\n## Usage\nText\n## License\nMIT")
    (tmp_path / "LICENSE").write_text("MIT")

    from app.services.analyzers.security import SecurityAnalyzer
    sec_res = await SecurityAnalyzer().analyze(tmp_path, {"owner": "test", "repo_name": "leaked"})
    assert sec_res.score < 100
    assert any(f.severity == "critical" for f in sec_res.findings)

@pytest.mark.asyncio
async def test_e2e_devops_empty_file_gaming_prevention(tmp_path: Path):
    """
    Adversarial Test: 0-byte fake Dockerfile and CI files must not count as valid DevOps specs.
    """
    # 0-byte empty Dockerfile
    (tmp_path / "Dockerfile").write_text("")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("")

    from app.services.analyzers.prod_readiness import ProdReadinessAnalyzer
    res = await ProdReadinessAnalyzer().analyze(tmp_path, {"owner": "test", "repo_name": "fake-devops"})
    assert res.metrics_json["has_ci_cd"] is False
    assert res.metrics_json["has_containerization"] is False
