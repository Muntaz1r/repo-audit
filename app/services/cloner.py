import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Tuple, Dict, Any
import httpx
from app.config import WORKSPACE_DIR, MAX_REPO_SIZE_MB, AUDIT_TIMEOUT_SECONDS

GITHUB_URL_REGEX = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git|/)?$"
)

def parse_github_url(url: str) -> Tuple[str, str]:
    """Extract owner and repo_name from a public GitHub URL."""
    cleaned = url.strip()
    match = GITHUB_URL_REGEX.match(cleaned)
    if not match:
        raise ValueError("Invalid GitHub URL. Must be formatted as https://github.com/owner/repository")
    owner, repo = match.group(1), match.group(2)
    return owner, repo

async def fetch_github_metadata(owner: str, repo: str) -> Dict[str, Any]:
    """
    Fetch public repository metadata via GitHub REST API.
    Gracefully falls back to direct clone metadata if GitHub API rate limit (403) is hit.
    """
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {"User-Agent": "RepoAudit-Platform"}
    
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(api_url, headers=headers)
            if response.status_code == 404:
                raise ValueError(f"Repository '{owner}/{repo}' not found or is private.")
            if response.status_code == 403:
                # Rate limit exceeded: fallback to minimal metadata and proceed with shallow clone
                print(f"[Cloner] GitHub API rate limit (403) hit for '{owner}/{repo}'. Falling back to direct clone.")
                return {
                    "owner": owner,
                    "repo_name": repo,
                    "default_branch": "main",
                    "stars_count": 0,
                    "primary_language": "Source",
                    "description": "Repository metadata obtained via direct clone (GitHub API rate-limited).",
                    "size_mb": 0.0,
                }
            if response.status_code != 200:
                raise ValueError(f"GitHub API error ({response.status_code}): {response.text}")
            
            data = response.json()
            size_kb = data.get("size", 0)
            size_mb = size_kb / 1024.0
            
            if size_mb > MAX_REPO_SIZE_MB:
                raise ValueError(f"Repository size ({size_mb:.1f} MB) exceeds maximum allowed threshold of {MAX_REPO_SIZE_MB} MB.")
            
            return {
                "owner": data.get("owner", {}).get("login", owner),
                "repo_name": data.get("name", repo),
                "default_branch": data.get("default_branch", "main"),
                "stars_count": data.get("stargazers_count", 0),
                "primary_language": data.get("language") or "Unknown",
                "description": data.get("description") or "",
                "size_mb": size_mb,
            }
    except ValueError:
        raise
    except Exception as e:
        # Fallback for network timeouts or connection errors to GitHub API
        print(f"[Cloner] GitHub API request failed: {e}. Falling back to direct clone.")
        return {
            "owner": owner,
            "repo_name": repo,
            "default_branch": "main",
            "stars_count": 0,
            "primary_language": "Source",
            "description": "Repository metadata obtained via direct clone.",
            "size_mb": 0.0,
        }

def shallow_clone_repo(repo_url: str, audit_id: str) -> Path:
    """
    Shallow-clones a repository into a sandboxed ephemeral workspace.
    Uses --depth 1 and --single-branch to minimize disk footprint.
    """
    target_dir = WORKSPACE_DIR / audit_id
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "git",
        "clone",
        "--depth", "1",
        "--single-branch",
        "--filter=blob:none",
        repo_url,
        str(target_dir),
    ]

    clone_env = os.environ.copy()
    clone_env["GIT_TERMINAL_PROMPT"] = "0"

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=AUDIT_TIMEOUT_SECONDS,
            check=True,
            env=clone_env,
        )
        return target_dir
    except subprocess.TimeoutExpired:
        cleanup_workspace(audit_id)
        raise TimeoutError(f"Git clone operation timed out after {AUDIT_TIMEOUT_SECONDS}s")
    except subprocess.CalledProcessError as e:
        stderr_msg = e.stderr.strip()
        # If it's an empty repo (0 commits or no HEAD ref), allow empty workspace
        if "empty repository" in stderr_msg or "Couldn't find remote ref" in stderr_msg or "remote HEAD refers to nonexistent ref" in stderr_msg:
            print(f"[Cloner] Cloned empty repository for audit {audit_id}.")
            return target_dir
        cleanup_workspace(audit_id)
        raise RuntimeError(f"Git clone failed: {stderr_msg}")

def cleanup_workspace(audit_id: str) -> None:
    """Guaranteed teardown of temporary workspace directory."""
    target_dir = WORKSPACE_DIR / audit_id
    if target_dir.exists():
        try:
            # Handle read-only files if git created any
            def on_rm_error(func, path, exc_info):
                os.chmod(path, 0o777)
                func(path)
            shutil.rmtree(target_dir, onerror=on_rm_error)
        except Exception:
            pass
