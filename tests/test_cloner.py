import pytest
from app.services.cloner import parse_github_url, cleanup_workspace
from app.config import WORKSPACE_DIR

def test_parse_github_url_valid():
    owner, repo = parse_github_url("https://github.com/expressjs/express")
    assert owner == "expressjs"
    assert repo == "express"

def test_parse_github_url_with_trailing_slash():
    owner, repo = parse_github_url("https://github.com/pallets/flask/")
    assert owner == "pallets"
    assert repo == "flask"

def test_parse_github_url_with_git_suffix():
    owner, repo = parse_github_url("https://github.com/psf/requests.git")
    assert owner == "psf"
    assert repo == "requests"

def test_parse_github_url_invalid():
    with pytest.raises(ValueError):
        parse_github_url("https://gitlab.com/user/repo")
    
    with pytest.raises(ValueError):
        parse_github_url("not-a-url")

def test_cleanup_workspace():
    test_audit_id = "test_cleanup_123"
    test_dir = WORKSPACE_DIR / test_audit_id
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / "sample.txt").write_text("hello")
    assert test_dir.exists()

    cleanup_workspace(test_audit_id)
    assert not test_dir.exists()
