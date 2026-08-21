import pytest
from pathlib import Path
from app.services.analyzers.security import SecurityAnalyzer, mask_secret

def test_mask_secret():
    assert mask_secret("AKIAIOSFODNN7EXAMPLE") == "AKIA************MPLE"
    assert mask_secret("ghp_1234567890abcdefghijklmnopqrstuvwxyz") == "ghp_********************************wxyz"
    assert mask_secret("short") == "******"

@pytest.mark.asyncio
async def test_security_analyzer_clean_repo(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.js").write_text("console.log('Hello World');")
    (tmp_path / "package.json").write_text('{"dependencies": {"lodash": "4.17.21"}}')

    analyzer = SecurityAnalyzer()
    result = await analyzer.analyze(tmp_path, {"owner": "test", "repo_name": "clean-repo"})

    assert result.pillar_key == "security"
    assert result.score == 100
    assert result.status == "PASS"
    assert len(result.findings) == 0
    assert result.metrics_json["secret_findings_count"] == 0
    assert result.metrics_json["vulnerability_findings_count"] == 0

@pytest.mark.asyncio
async def test_security_analyzer_detects_aws_key(tmp_path: Path):
    (tmp_path / "config.py").write_text("AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\nAWS_SECRET = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'")

    analyzer = SecurityAnalyzer()
    result = await analyzer.analyze(tmp_path, {"owner": "test", "repo_name": "leaky-repo"})

    assert result.pillar_key == "security"
    assert result.score < 100
    assert len(result.findings) >= 1
    
    aws_finding = next((f for f in result.findings if "AWS Access Key" in f.title), None)
    assert aws_finding is not None
    assert aws_finding.severity == "critical"
    # Ensure raw secret is not in snippet or description
    assert "AKIAIOSFODNN7EXAMPLE" not in aws_finding.description
    assert "AKIA" in aws_finding.description

@pytest.mark.asyncio
async def test_security_analyzer_detects_vulnerable_dependency(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"dependencies": {"lodash": "4.17.15", "axios": "0.21.0"}}')

    analyzer = SecurityAnalyzer()
    result = await analyzer.analyze(tmp_path, {"owner": "test", "repo_name": "vuln-repo"})

    assert result.pillar_key == "security"
    assert result.score < 80
    assert result.status in ["WARN", "FAIL"]
    assert len(result.findings) >= 2
    
    lodash_vuln = next((f for f in result.findings if "lodash" in f.title), None)
    assert lodash_vuln is not None
    assert "CVE-2021-23337" in lodash_vuln.title
    assert "4.17.21" in lodash_vuln.recommendation
