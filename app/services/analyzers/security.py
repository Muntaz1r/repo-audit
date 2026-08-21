import os
import re
import json
import math
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from app.services.analyzers.base import BasePillarAnalyzer, PillarResult, FindingResult

IGNORE_DIRS = {
    ".git", "node_modules", "dist", "build", "vendor", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "coverage", ".next", ".nuxt", "target"
}

# Regex patterns for high-confidence secrets
SECRET_PATTERNS = [
    (
        "AWS Access Key ID",
        re.compile(r"(?:A3T[A-Z0-9]|AKIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}"),
        "critical",
        "Hardcoded AWS Access Key detected. Exposes cloud infrastructure to unauthorized access.",
        "Immediately revoke this key in AWS IAM and use environment variables or IAM Roles instead."
    ),
    (
        "GitHub Personal Access Token",
        re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,255}"),
        "critical",
        "Hardcoded GitHub Token detected. Exposes source repositories and organization permissions.",
        "Revoke the token immediately on GitHub Settings and rotate with repository secrets."
    ),
    (
        "Private Key",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
        "critical",
        "Cryptographic Private Key committed to source code.",
        "Remove the private key from source control and generate a new key pair immediately."
    ),
    (
        "Slack Bot/User Token",
        re.compile(r"xox[baprs]-[0-9a-zA-Z]{10,48}"),
        "critical",
        "Slack API token committed to repository.",
        "Revoke token in Slack App Management and inject via secure vault or environment variables."
    ),
    (
        "Google API Key",
        re.compile(r"AIza[0-9A-Za-z\\-_]{35}"),
        "warning",
        "Hardcoded Google API key found in source code.",
        "Restrict API key scopes in Google Cloud Console or move to server-side environment variables."
    ),
    (
        "Generic Secret Assignment",
        re.compile(r"(?:api_key|apikey|secret_key|private_key|auth_token|password|db_pass)\s*[:=]\s*['\"][A-Za-z0-9_\-+=/]{16,}['\"]", re.IGNORECASE),
        "warning",
        "Hardcoded credential or authentication secret assignment detected.",
        "Extract secret to environment variables or an external secret manager."
    )
]

# Known insecure packages / patterns (vulnerability heuristic database)
KNOWN_VULNERABILITIES = [
    {"pkg": "lodash", "max_version": "4.17.20", "cve": "CVE-2021-23337", "title": "Prototype Pollution in lodash", "fixed": "4.17.21"},
    {"pkg": "axios", "max_version": "0.21.0", "cve": "CVE-2020-28168", "title": "SSRF in axios", "fixed": "0.21.1"},
    {"pkg": "jsonwebtoken", "max_version": "8.5.1", "cve": "CVE-2022-23529", "title": "Insecure Key Validation in jsonwebtoken", "fixed": "9.0.0"},
    {"pkg": "urllib3", "max_version": "1.26.4", "cve": "CVE-2021-33503", "title": "Catastrophic ReDoS in urllib3", "fixed": "1.26.5"},
    {"pkg": "requests", "max_version": "2.19.1", "cve": "CVE-2018-18074", "title": "HTTP Basic Auth Leak in requests", "fixed": "2.20.0"},
    {"pkg": "django", "max_version": "2.2.27", "cve": "CVE-2022-28346", "title": "SQL Injection in QuerySet.annotate()", "fixed": "2.2.28"},
    {"pkg": "flask", "max_version": "0.12.2", "cve": "CVE-2018-1000656", "title": "Denial of Service in Flask JSON Encoding", "fixed": "0.12.3"},
    {"pkg": "log4j", "max_version": "2.14.1", "cve": "CVE-2021-44228", "title": "Log4Shell Remote Code Execution", "fixed": "2.15.0"}
]

def mask_secret(secret_str: str) -> str:
    """Masks secret values so raw credentials never get logged or stored in plain text."""
    clean = secret_str.strip("'\"")
    if len(clean) <= 8:
        return "******"
    prefix = clean[:4]
    suffix = clean[-4:]
    stars = "*" * max(len(clean) - 8, 4)
    return f"{prefix}{stars}{suffix}"

class SecurityAnalyzer(BasePillarAnalyzer):
    @property
    def pillar_key(self) -> str:
        return "security"

    @property
    def name(self) -> str:
        return "Security & Vulnerability"

    async def analyze(self, repo_dir: Path, metadata: Dict[str, Any]) -> PillarResult:
        findings: List[FindingResult] = []
        secret_findings_count = 0
        vuln_findings_count = 0
        total_files_scanned = 0
        total_dependencies_scanned = 0

        score = 100

        # 1. Scan source files for hardcoded secrets
        for root, dirs, files in os.walk(repo_dir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

            for file in files:
                file_path = Path(root) / file
                rel_path = str(file_path.relative_to(repo_dir)).replace("\\", "/")

                # Skip symlinks or non-text or huge files
                if file_path.is_symlink() or file_path.suffix.lower() in [".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".tar", ".gz", ".woff", ".ttf", ".lock", ".bin", ".exe", ".so", ".dylib", ".wasm"]:
                    continue

                try:
                    if file_path.stat().st_size > 500 * 1024:  # >500KB
                        continue
                    # Read binary header to check for binary / null bytes
                    with open(file_path, "rb") as f:
                        header = f.read(1024)
                        if b"\x00" in header:  # Binary file masquerading with text extension
                            continue

                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    total_files_scanned += 1
                except Exception:
                    continue

                lines = content.splitlines()
                for line_idx, line in enumerate(lines, start=1):
                    # Skip extremely long minified lines (>2000 chars) to prevent ReDoS latency
                    if len(line) > 2000:
                        continue

                    for name, pattern, severity, desc, rec in SECRET_PATTERNS:
                        match = pattern.search(line)
                        if match:
                            raw_match = match.group(0)
                            masked = mask_secret(raw_match)
                            
                            # Mask line in snippet
                            snippet = line.replace(raw_match, masked).strip()
                            if len(snippet) > 120:
                                snippet = snippet[:120] + "..."

                            penalty = 25 if severity == "critical" else 10
                            score -= penalty
                            secret_findings_count += 1

                            findings.append(FindingResult(
                                severity=severity,
                                title=f"Exposed Secret: {name}",
                                description=f"Potential {name} detected in {rel_path} on line {line_idx}. Value has been automatically masked: `{masked}`",
                                file_path=rel_path,
                                line_start=line_idx,
                                line_end=line_idx,
                                code_snippet=snippet,
                                impact=desc,
                                recommendation=rec
                            ))
                            break  # Avoid double matching the exact same line

        # 2. Scan dependency manifests for vulnerable dependencies
        manifest_deps = self._extract_dependencies(repo_dir)
        total_dependencies_scanned = len(manifest_deps)

        for dep_name, (version_str, file_source) in manifest_deps.items():
            for vuln in KNOWN_VULNERABILITIES:
                if dep_name.lower() == vuln["pkg"].lower():
                    # Check version match or pin
                    if self._is_version_vulnerable(version_str, vuln["max_version"]):
                        score -= 20
                        vuln_findings_count += 1
                        findings.append(FindingResult(
                            severity="critical",
                            title=f"Vulnerable Dependency: {dep_name} ({vuln['cve']})",
                            description=f"Package '{dep_name}' pinned to '{version_str}' in {file_source} is affected by {vuln['cve']}: {vuln['title']}.",
                            file_path=file_source,
                            line_start=1,
                            line_end=1,
                            code_snippet=f'"{dep_name}": "{version_str}"  // Affected: <= {vuln["max_version"]}',
                            impact=f"Security risk: {vuln['title']}. May allow remote exploit or service degradation.",
                            recommendation=f"Upgrade '{dep_name}' to version {vuln['fixed']} or higher immediately."
                        ))

        # Check for presence of .env in repo
        env_files = list(repo_dir.glob(".env")) + list(repo_dir.glob(".env.local"))
        for env_f in env_files:
            rel = str(env_f.relative_to(repo_dir)).replace("\\", "/")
            score -= 20
            findings.append(FindingResult(
                severity="critical",
                title="Committed Environment File (.env)",
                description=f"Found '{rel}' committed directly into git repository history.",
                file_path=rel,
                line_start=1,
                line_end=1,
                impact="Environment configuration files often contain database credentials, private API keys, and local secrets.",
                recommendation="Remove .env from git history using git filter-branch/BFG and add .env to .gitignore."
            ))

        score = max(min(score, 100), 10)
        status = "PASS" if score >= 80 else ("WARN" if score >= 60 else "FAIL")

        metrics = {
            "total_files_scanned": total_files_scanned,
            "total_dependencies_scanned": total_dependencies_scanned,
            "secret_findings_count": secret_findings_count,
            "vulnerability_findings_count": vuln_findings_count,
            "security_grade": "A" if score >= 90 else ("B" if score >= 80 else ("C" if score >= 70 else "F")),
            "secret_scanner_status": "CLEAN" if secret_findings_count == 0 else f"{secret_findings_count} EXPOSED SECRETS",
            "dependency_scanner_status": "CLEAN" if vuln_findings_count == 0 else f"{vuln_findings_count} VULNERABLE PACKAGES"
        }

        return PillarResult(
            pillar_key=self.pillar_key,
            score=score,
            status=status,
            metrics_json=metrics,
            findings=findings
        )

    def _extract_dependencies(self, repo_dir: Path) -> Dict[str, Tuple[str, str]]:
        """Extracts packages and version pins across package.json, requirements.txt, and go.mod."""
        deps: Dict[str, Tuple[str, str]] = {}

        # 1. package.json
        pkg_json = repo_dir / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8", errors="ignore"))
                all_deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                for k, v in all_deps.items():
                    deps[k] = (str(v).strip("^~>=< "), "package.json")
            except Exception:
                pass

        # 2. requirements.txt
        req_txt = repo_dir / "requirements.txt"
        if req_txt.exists():
            try:
                for line in req_txt.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        if "==" in line:
                            p, v = line.split("==", 1)
                            deps[p.strip()] = (v.strip(), "requirements.txt")
                        elif ">=" in line:
                            p, v = line.split(">=", 1)
                            deps[p.strip()] = (v.strip(), "requirements.txt")
                        else:
                            p = re.split(r"[><=~]", line)[0].strip()
                            if p:
                                deps[p] = ("*", "requirements.txt")
            except Exception:
                pass

        return deps

    def _is_version_vulnerable(self, version_str: str, max_vuln_version: str) -> bool:
        """Simple semver comparison heuristic for known vulnerable versions."""
        if version_str in ["*", "latest", ""]:
            return False
        
        # Clean versions
        v_parts = re.findall(r"\d+", version_str)
        max_parts = re.findall(r"\d+", max_vuln_version)

        if not v_parts:
            return False

        try:
            v_nums = [int(x) for x in v_parts[:3]]
            max_nums = [int(x) for x in max_parts[:3]]

            # Pad
            while len(v_nums) < 3:
                v_nums.append(0)
            while len(max_nums) < 3:
                max_nums.append(0)

            return v_nums <= max_nums
        except Exception:
            return False
