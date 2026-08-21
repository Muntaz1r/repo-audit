import os
import re
import ast
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from app.services.analyzers.base import BasePillarAnalyzer, PillarResult, FindingResult

IGNORE_DIRS = {
    ".git", "node_modules", "dist", "build", "vendor", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "coverage", ".next", ".nuxt", "target"
}

README_SECTION_PATTERNS = {
    "overview": re.compile(r"#+\s*(overview|about|introduction|what is|description)", re.IGNORECASE),
    "installation": re.compile(r"#+\s*(install|installation|setup|getting started|getting-started|prerequisites)", re.IGNORECASE),
    "usage": re.compile(r"#+\s*(usage|quickstart|quick start|how to use|example|examples|basic usage)", re.IGNORECASE),
    "configuration": re.compile(r"#+\s*(config|configuration|environment|options|settings|api|api reference)", re.IGNORECASE),
    "contributing": re.compile(r"#+\s*(contributing|development|contribute)", re.IGNORECASE),
    "license": re.compile(r"#+\s*(license|licence)", re.IGNORECASE)
}

class DocumentationAnalyzer(BasePillarAnalyzer):
    @property
    def pillar_key(self) -> str:
        return "docs"

    @property
    def name(self) -> str:
        return "Documentation Quality"

    async def analyze(self, repo_dir: Path, metadata: Dict[str, Any]) -> PillarResult:
        findings: List[FindingResult] = []
        score = 100

        # 1. README Analysis
        readme_path, readme_content = self._find_readme(repo_dir)
        readme_checklist: Dict[str, bool] = {}
        readme_word_count = 0

        if not readme_path or not readme_content:
            score -= 40
            readme_checklist = {
                "has_readme": False,
                "overview": False,
                "installation": False,
                "usage": False,
                "configuration": False,
                "license": False
            }
            findings.append(FindingResult(
                severity="critical",
                title="Missing Repository README",
                description="No README.md (or equivalent) was found at the root of the repository.",
                file_path="README.md",
                line_start=1,
                line_end=1,
                impact="Severe onboarding friction. New contributors and reviewers cannot determine purpose or setup instructions.",
                recommendation="Create a comprehensive README.md with Overview, Installation, Usage, and License sections."
            ))
        else:
            readme_word_count = len(readme_content.split())
            readme_checklist["has_readme"] = True

            # Check individual sections (ensuring non-empty body content follows the heading)
            for section_name, pattern in README_SECTION_PATTERNS.items():
                match = pattern.search(readme_content)
                if match:
                    # Verify text exists after heading before next heading or EOF
                    post_heading = readme_content[match.end():]
                    next_heading = re.search(r"\n#+\s+", post_heading)
                    section_body = post_heading[:next_heading.start()] if next_heading else post_heading
                    has_substantive_body = len(section_body.strip().split()) >= 2 or "```" in section_body or "`" in section_body
                    readme_checklist[section_name] = has_substantive_body
                else:
                    readme_checklist[section_name] = False

            # Penalize missing key sections
            if not readme_checklist.get("installation"):
                score -= 10
                findings.append(FindingResult(
                    severity="warning",
                    title="Missing Installation Instructions in README",
                    description="The README does not contain a dedicated Installation or Setup section.",
                    file_path=str(readme_path.relative_to(repo_dir)).replace("\\", "/"),
                    line_start=1,
                    line_end=1,
                    impact="Users cannot easily reproduce environment or build the project.",
                    recommendation="Add an 'Installation' or 'Getting Started' section with step-by-step commands."
                ))

            if not readme_checklist.get("usage"):
                score -= 10
                findings.append(FindingResult(
                    severity="warning",
                    title="Missing Usage / Quickstart Examples in README",
                    description="The README does not contain a Quickstart or Usage section with code examples.",
                    file_path=str(readme_path.relative_to(repo_dir)).replace("\\", "/"),
                    line_start=1,
                    line_end=1,
                    impact="Steep learning curve for developers trying to adopt this repository.",
                    recommendation="Add a 'Quickstart' or 'Usage' section with working snippet examples."
                ))

            if readme_word_count < 30:
                score -= 15
                findings.append(FindingResult(
                    severity="warning",
                    title="Very Short or Placeholder README",
                    description=f"The README is only {readme_word_count} words long.",
                    file_path=str(readme_path.relative_to(repo_dir)).replace("\\", "/"),
                    line_start=1,
                    line_end=1,
                    impact="Provides insufficient documentation for reviewers or prospective users.",
                    recommendation="Expand the README to describe architecture, dependencies, and execution."
                ))

        # 2. License File Check
        license_file = self._find_license(repo_dir)
        has_license = bool(license_file or readme_checklist.get("license"))
        if not has_license:
            score -= 15
            findings.append(FindingResult(
                severity="warning",
                title="Missing Software License",
                description="No LICENSE file or explicit license declaration found in the repository.",
                file_path="LICENSE",
                line_start=1,
                line_end=1,
                impact="Without an explicit open-source license, standard copyright applies and reuse may be restricted.",
                recommendation="Add an open-source license file (e.g. MIT, Apache-2.0, BSD-3-Clause) in the root directory."
            ))

        # 3. Inline Docstring Coverage Analysis
        total_symbols, documented_symbols = self._calculate_docstring_coverage(repo_dir)
        docstring_coverage = round((documented_symbols / total_symbols * 100), 1) if total_symbols > 0 else 100.0

        if total_symbols > 5 and docstring_coverage < 30.0:
            score -= 15
            findings.append(FindingResult(
                severity="warning",
                title=f"Low Public API Docstring Coverage ({docstring_coverage}%)",
                description=f"Only {documented_symbols} of {total_symbols} detected public functions/classes contain docstrings or JSDoc comments.",
                impact="Maintenance bottleneck. Undocumented internal and exported APIs slow down onboarding.",
                recommendation="Add docstrings / JSDoc comments explaining parameters and return values for public functions."
            ))

        score = max(min(score, 100), 10)
        status = "PASS" if score >= 80 else ("WARN" if score >= 60 else "FAIL")

        metrics = {
            "has_readme": readme_checklist.get("has_readme", False),
            "readme_word_count": readme_word_count,
            "has_license": has_license,
            "license_file": str(license_file.relative_to(repo_dir)).replace("\\", "/") if license_file else None,
            "readme_sections": readme_checklist,
            "total_symbols_scanned": total_symbols,
            "documented_symbols": documented_symbols,
            "docstring_coverage_pct": docstring_coverage,
            "documentation_grade": "A" if score >= 90 else ("B" if score >= 80 else ("C" if score >= 70 else "F"))
        }

        return PillarResult(
            pillar_key=self.pillar_key,
            score=score,
            status=status,
            metrics_json=metrics,
            findings=findings
        )

    def _find_readme(self, repo_dir: Path) -> Tuple[Optional[Path], Optional[str]]:
        for name in ["README.md", "README.rst", "README.txt", "readme.md", "ReadMe.md", "README"]:
            p = repo_dir / name
            if p.exists():
                try:
                    return p, p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    pass
        return None, None

    def _find_license(self, repo_dir: Path) -> Optional[Path]:
        for name in ["LICENSE", "LICENSE.md", "LICENSE.txt", "license", "COPYING", "UNLICENSE"]:
            p = repo_dir / name
            if p.exists():
                return p
        return None

    def _calculate_docstring_coverage(self, repo_dir: Path) -> Tuple[int, int]:
        total_symbols = 0
        documented_symbols = 0

        for root, dirs, files in os.walk(repo_dir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

            for file in files:
                file_path = Path(root) / file
                ext = file_path.suffix.lower()

                # Python AST Inspection
                if ext == ".py":
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        tree = ast.parse(content)
                        for node in ast.walk(tree):
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                                if not node.name.startswith("_"):  # Public symbols
                                    total_symbols += 1
                                    if ast.get_docstring(node):
                                        documented_symbols += 1
                    except Exception:
                        pass

                # JS / TS Inspection
                elif ext in [".js", ".ts", ".jsx", ".tsx"]:
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        lines = content.splitlines()
                        for idx, line in enumerate(lines):
                            # Public function / class pattern
                            if re.search(r"^(export\s+)?(async\s+)?function\s+([a-zA-Z0-9_]+)", line.strip()) or \
                               re.search(r"^(export\s+)?class\s+([a-zA-Z0-9_]+)", line.strip()):
                                total_symbols += 1
                                # Look for JSDoc comment in preceding 3 lines
                                prev_lines = " ".join(lines[max(0, idx-3):idx])
                                if "*/" in prev_lines or "//" in prev_lines:
                                    documented_symbols += 1
                    except Exception:
                        pass

                # Go Inspection (Exported identifiers begin with uppercase letter)
                elif ext == ".go":
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        lines = content.splitlines()
                        for idx, line in enumerate(lines):
                            if re.search(r"^func\s+([A-Z][a-zA-Z0-9_]*)", line.strip()) or \
                               re.search(r"^type\s+([A-Z][a-zA-Z0-9_]*)\s+(struct|interface)", line.strip()):
                                total_symbols += 1
                                prev_lines = " ".join(lines[max(0, idx-2):idx])
                                if "//" in prev_lines or "/*" in prev_lines:
                                    documented_symbols += 1
                    except Exception:
                        pass

                # Rust Inspection (pub fn, pub struct, pub enum, pub trait)
                elif ext == ".rs":
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        lines = content.splitlines()
                        for idx, line in enumerate(lines):
                            if re.search(r"^pub(\s+\(crate\))?\s+(fn|struct|enum|trait)\s+([a-zA-Z0-9_]+)", line.strip()):
                                total_symbols += 1
                                prev_lines = " ".join(lines[max(0, idx-2):idx])
                                if "///" in prev_lines or "/**" in prev_lines or "//" in prev_lines:
                                    documented_symbols += 1
                    except Exception:
                        pass

                # Java Inspection (public class, public method)
                elif ext == ".java":
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        lines = content.splitlines()
                        for idx, line in enumerate(lines):
                            if re.search(r"^public\s+(class|interface|enum)\s+([a-zA-Z0-9_]+)", line.strip()) or \
                               re.search(r"^public\s+[a-zA-Z0-9_<>,\[\]]+\s+([a-zA-Z0-9_]+)\s*\(", line.strip()):
                                total_symbols += 1
                                prev_lines = " ".join(lines[max(0, idx-3):idx])
                                if "*/" in prev_lines or "//" in prev_lines:
                                    documented_symbols += 1
                    except Exception:
                        pass

        return total_symbols, documented_symbols
