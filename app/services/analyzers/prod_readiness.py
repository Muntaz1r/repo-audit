import os
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple
from app.services.analyzers.base import BasePillarAnalyzer, PillarResult, FindingResult

IGNORE_DIRS = {
    ".git", "node_modules", "dist", "build", "vendor", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "coverage", ".next", ".nuxt", "target"
}

LOGGING_PACKAGES_OR_CALLS = [
    # Python
    re.compile(r"(?:import\s+logging|from\s+logging|structlog|loguru)", re.IGNORECASE),
    # Node.js
    re.compile(r"(?:require\(['\"](?:winston|pino|morgan|bunyan|loglevel)['\"]\)|from\s+['\"](?:winston|pino|morgan)['\"])", re.IGNORECASE),
    # Go
    re.compile(r"(?:\"go\.uber\.org\/zap\"|\"github\.com\/sirupsen\/logrus\"|\"log\/slog\")", re.IGNORECASE),
    # Rust
    re.compile(r"(?:tracing|log::|env_logger)", re.IGNORECASE)
]

class ProdReadinessAnalyzer(BasePillarAnalyzer):
    @property
    def pillar_key(self) -> str:
        return "prod_readiness"

    @property
    def name(self) -> str:
        return "Production Readiness"

    async def analyze(self, repo_dir: Path, metadata: Dict[str, Any]) -> PillarResult:
        findings: List[FindingResult] = []
        score = 100

        # 1. CI/CD Pipeline Detection
        ci_files = self._detect_ci_cd(repo_dir)
        has_ci = len(ci_files) > 0
        if not has_ci:
            score -= 25
            findings.append(FindingResult(
                severity="warning",
                title="Missing Automated CI/CD Workflows",
                description="No GitHub Actions (.github/workflows), GitLab CI, or CircleCI pipeline configurations detected.",
                file_path=".github/workflows",
                line_start=1,
                line_end=1,
                impact="Pull requests and releases are not automatically built, linted, or tested before merging.",
                recommendation="Add a GitHub Actions workflow (.github/workflows/ci.yml) to run test suites on each push and pull request."
            ))

        # 2. Containerization Detection
        docker_files = self._detect_containerization(repo_dir)
        has_docker = len(docker_files) > 0
        if not has_docker:
            score -= 15
            findings.append(FindingResult(
                severity="info",
                title="No Containerization Configuration Found",
                description="No Dockerfile, docker-compose.yml, or Containerfile detected in the repository.",
                file_path="Dockerfile",
                line_start=1,
                line_end=1,
                impact="May increase deployment inconsistency across different server environments.",
                recommendation="Add a standard multi-stage Dockerfile to ensure reproducible containerized builds."
            ))

        # 3. Environment & Git Hygiene
        gitignore = (repo_dir / ".gitignore").exists()
        dockerignore = (repo_dir / ".dockerignore").exists()
        env_example = (repo_dir / ".env.example").exists() or (repo_dir / ".env.sample").exists() or (repo_dir / ".env.template").exists()

        if not gitignore:
            score -= 15
            findings.append(FindingResult(
                severity="warning",
                title="Missing .gitignore Configuration",
                description="No .gitignore file found at the root of the repository.",
                file_path=".gitignore",
                line_start=1,
                line_end=1,
                impact="High risk of accidentally committing build artifacts, dependencies, or local credentials.",
                recommendation="Add a comprehensive language-specific .gitignore file."
            ))

        if not env_example and not (repo_dir / ".env").exists():
            # Only flag if there are config needs
            pass

        # 4. Structured Logging & Observability Check
        has_logging = self._detect_structured_logging(repo_dir)
        if not has_logging:
            score -= 15
            findings.append(FindingResult(
                severity="info",
                title="No Structured Logging Framework Detected",
                description="Code appears to use raw console output (console.log / print) rather than structured loggers (winston, pino, structlog, loguru).",
                file_path=metadata.get("primary_language", "source"),
                line_start=1,
                line_end=1,
                impact="Raw standard output makes log parsing, filtering, and cloud observability in production more difficult.",
                recommendation="Adopt a structured JSON logging framework for production error tracing."
            ))

        # 5. Dependency Lockfile Check
        has_lockfile = (
            (repo_dir / "package-lock.json").exists() or
            (repo_dir / "yarn.lock").exists() or
            (repo_dir / "pnpm-lock.yaml").exists() or
            (repo_dir / "poetry.lock").exists() or
            (repo_dir / "Pipfile.lock").exists() or
            (repo_dir / "Cargo.lock").exists() or
            (repo_dir / "go.sum").exists()
        )
        if not has_lockfile and len(list(repo_dir.glob("*.json"))) > 0:
            score -= 10
            findings.append(FindingResult(
                severity="warning",
                title="Missing Deterministic Dependency Lockfile",
                description="No package-lock.json, yarn.lock, Cargo.lock, or poetry.lock found.",
                file_path="package-lock.json",
                line_start=1,
                line_end=1,
                impact="Builds across different CI runners may install differing dependency versions, causing non-reproducible bugs.",
                recommendation="Commit your dependency lockfile to ensure deterministic reproducible builds."
            ))

        score = max(min(score, 100), 10)
        status = "PASS" if score >= 80 else ("WARN" if score >= 60 else "FAIL")

        metrics = {
            "has_ci_cd": has_ci,
            "ci_files": ci_files,
            "has_containerization": has_docker,
            "container_files": docker_files,
            "has_gitignore": gitignore,
            "has_dockerignore": dockerignore,
            "has_env_example": env_example,
            "has_structured_logging": has_logging,
            "has_deterministic_lockfile": has_lockfile,
            "prod_readiness_grade": "A" if score >= 90 else ("B" if score >= 80 else ("C" if score >= 70 else "F"))
        }

        return PillarResult(
            pillar_key=self.pillar_key,
            score=score,
            status=status,
            metrics_json=metrics,
            findings=findings
        )

    def _detect_ci_cd(self, repo_dir: Path) -> List[str]:
        found = []
        # GitHub Actions (ensure non-empty with jobs / on directive)
        gh_wf = repo_dir / ".github" / "workflows"
        if gh_wf.exists() and gh_wf.is_dir():
            for f in list(gh_wf.glob("*.yml")) + list(gh_wf.glob("*.yaml")):
                try:
                    if f.stat().st_size > 15:
                        content = f.read_text(encoding="utf-8", errors="ignore")
                        if "on:" in content or "jobs:" in content or "steps:" in content:
                            found.append(f".github/workflows/{f.name}")
                except Exception:
                    pass
        
        # GitLab CI
        gl = repo_dir / ".gitlab-ci.yml"
        if gl.exists() and gl.stat().st_size > 15:
            found.append(".gitlab-ci.yml")

        # CircleCI
        circle = repo_dir / ".circleci" / "config.yml"
        if circle.exists() and circle.stat().st_size > 15:
            found.append(".circleci/config.yml")

        # Jenkins
        jenkins = repo_dir / "Jenkinsfile"
        if jenkins.exists() and jenkins.stat().st_size > 15:
            found.append("Jenkinsfile")

        # Azure Pipelines
        azure = repo_dir / "azure-pipelines.yml"
        if azure.exists() and azure.stat().st_size > 15:
            found.append("azure-pipelines.yml")

        return found

    def _detect_containerization(self, repo_dir: Path) -> List[str]:
        found = []
        for name in ["Dockerfile", "Dockerfile.dev", "Dockerfile.prod", "docker-compose.yml", "docker-compose.yaml", "compose.yaml", "Containerfile"]:
            p = repo_dir / name
            if p.exists() and p.stat().st_size > 10:
                try:
                    content = p.read_text(encoding="utf-8", errors="ignore")
                    if "FROM " in content or "services:" in content or "version:" in content or "image:" in content:
                        found.append(name)
                except Exception:
                    pass
        return found

    def _detect_structured_logging(self, repo_dir: Path) -> bool:
        for root, dirs, files in os.walk(repo_dir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in [".py", ".js", ".ts", ".go", ".rs"]:
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")[:3000]
                        for pat in LOGGING_PACKAGES_OR_CALLS:
                            if pat.search(content):
                                return True
                    except Exception:
                        pass
        return False
