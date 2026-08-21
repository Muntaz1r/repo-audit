import os
import re
import ast
from pathlib import Path
from typing import Dict, Any, List, Tuple
from app.services.analyzers.base import BasePillarAnalyzer, PillarResult, FindingResult

IGNORE_DIRS = {
    ".git", "node_modules", "dist", "build", "vendor", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "coverage", ".next", ".nuxt", "target"
}

CODE_EXTENSIONS = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript (React)",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".cpp": "C++",
    ".c": "C",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
}

TEST_PATTERNS = re.compile(r"(test_|_test|\.test\.|\.spec\.|tests/|test/|__tests__/)", re.IGNORECASE)

class CodeEvaluationAnalyzer(BasePillarAnalyzer):
    @property
    def pillar_key(self) -> str:
        return "code_eval"

    @property
    def name(self) -> str:
        return "Code Evaluation"

    async def analyze(self, repo_dir: Path, metadata: Dict[str, Any]) -> PillarResult:
        files_by_lang: Dict[str, int] = {}
        total_loc = 0
        total_comments = 0
        total_blanks = 0
        total_code_files = 0
        test_files_count = 0
        source_files_count = 0

        complexities: List[int] = []
        findings: List[FindingResult] = []

        # Traverse repository files
        for root, dirs, files in os.walk(repo_dir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for file in files:
                file_path = Path(root) / file
                rel_path = str(file_path.relative_to(repo_dir)).replace("\\", "/")
                ext = file_path.suffix.lower()

                if ext in CODE_EXTENSIONS:
                    total_code_files += 1
                    lang = CODE_EXTENSIONS[ext]
                    files_by_lang[lang] = files_by_lang.get(lang, 0) + 1

                    # Skip binary files masquerading as code
                    try:
                        with open(file_path, "rb") as f:
                            if b"\x00" in f.read(1024):
                                continue
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            lines = f.readlines()
                    except Exception:
                        continue

                    is_test = bool(TEST_PATTERNS.search(rel_path))
                    file_content = "".join(lines)
                    has_real_tests = bool(re.search(r"(?:def\s+test_|async\s+def\s+test_|func\s+Test|fn\s+test_|it\s*\(|describe\s*\(|test\s*\(|assert\s+|expect\s*\()", file_content))

                    if is_test:
                        if has_real_tests or len(lines) > 5:
                            test_files_count += 1
                    else:
                        source_files_count += 1

                    file_loc = len(lines)
                    total_loc += file_loc

                    # Check for large file smell (> 500 LOC)
                    if file_loc > 500 and not is_test:
                        findings.append(FindingResult(
                            severity="warning",
                            title=f"Large Source File Exceeds 500 Lines ({file_loc} LOC)",
                            description=f"File '{rel_path}' contains {file_loc} lines of code. Large files often indicate violation of the Single Responsibility Principle.",
                            file_path=rel_path,
                            line_start=1,
                            line_end=file_loc,
                            code_snippet=f"// File: {rel_path} ({file_loc} lines)",
                            impact="High maintenance overhead and increased merge conflict frequency for reviewers.",
                            recommendation="Decompose this module into smaller cohesive sub-modules or separate business logic from I/O."
                        ))

                    # Analyze complexity and nesting per language
                    if ext == ".py":
                        self._analyze_python_file(lines, rel_path, findings, complexities)
                    else:
                        self._analyze_generic_code_file(lines, rel_path, findings, complexities)

        avg_complexity = round(sum(complexities) / len(complexities), 1) if complexities else 2.5
        test_ratio = round(test_files_count / max(source_files_count, 1), 2)

        # Evaluate test presence finding
        if source_files_count > 5 and test_files_count == 0:
            findings.append(FindingResult(
                severity="critical",
                title="Zero Automated Test Files Detected",
                description="The repository contains multiple source files but no automated test files matching common test conventions (*.test.*, *.spec.*, test_*.py, tests/).",
                file_path=None,
                impact="Severe regression risk. Non-author reviewers cannot verify functionality without automated verification suites.",
                recommendation="Establish a test suite using pytest, Jest, or native language runners."
            ))
        elif source_files_count > 10 and test_ratio < 0.15:
            findings.append(FindingResult(
                severity="warning",
                title=f"Low Test-to-Source File Ratio ({test_ratio}:1)",
                description=f"Detected {test_files_count} test files for {source_files_count} source files (recommended ratio: > 0.3:1).",
                impact="Partial test coverage increases the likelihood of unverified edge cases in production.",
                recommendation="Increase test coverage for core business logic and routing layers."
            ))

        # Calculate Maintainability Index & Score
        score = 100
        for f in findings:
            if f.severity == "critical":
                score -= 15
            elif f.severity == "warning":
                score -= 5
            elif f.severity == "info":
                score -= 2

        if avg_complexity > 12:
            score -= 15
        elif avg_complexity > 8:
            score -= 8

        if test_ratio < 0.1 and source_files_count > 5:
            score -= 10

        score = max(min(score, 100), 10)
        status = "PASS" if score >= 80 else ("WARN" if score >= 60 else "FAIL")

        metrics = {
            "total_loc": total_loc,
            "total_code_files": total_code_files,
            "source_files_count": source_files_count,
            "test_files_count": test_files_count,
            "test_to_source_ratio": test_ratio,
            "avg_cyclomatic_complexity": avg_complexity,
            "maintainability_index": min(max(int(100 - (avg_complexity * 3.5)), 20), 98),
            "languages": files_by_lang,
            "findings_count": {
                "critical": sum(1 for f in findings if f.severity == "critical"),
                "warning": sum(1 for f in findings if f.severity == "warning"),
                "info": sum(1 for f in findings if f.severity == "info"),
            }
        }

        return PillarResult(
            pillar_key=self.pillar_key,
            score=score,
            status=status,
            metrics_json=metrics,
            findings=findings
        )

    def _analyze_python_file(self, lines: List[str], rel_path: str, findings: List[FindingResult], complexities: List[int]):
        source = "".join(lines)
        try:
            tree = ast.parse(source)
        except Exception:
            self._analyze_generic_code_file(lines, rel_path, findings, complexities)
            return

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_name = node.name
                start_line = node.lineno
                end_line = getattr(node, "end_lineno", start_line + 10)
                fn_len = end_line - start_line + 1

                # Calculate cyclomatic complexity (branches + 1)
                complexity = 1
                for child in ast.walk(node):
                    if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.ExceptHandler, ast.With, ast.Assert)):
                        complexity += 1
                    elif isinstance(child, ast.BoolOp):
                        complexity += len(child.values) - 1

                complexities.append(complexity)

                # High complexity finding
                if complexity > 10:
                    snippet = self._get_snippet(lines, start_line, min(start_line + 8, len(lines)))
                    findings.append(FindingResult(
                        severity="warning" if complexity < 18 else "critical",
                        title=f"High Cyclomatic Complexity ({complexity}) in function '{fn_name}'",
                        description=f"Function '{fn_name}' contains {complexity} independent execution paths due to nested conditionals and branching logic.",
                        file_path=rel_path,
                        line_start=start_line,
                        line_end=end_line,
                        code_snippet=snippet,
                        impact="Dramatically increases cyclomatic testing combinations and cognitive burden for non-author reviewers.",
                        recommendation="Refactor branching paths using guard clauses, lookup dictionaries, or extracting helper functions."
                    ))

                # Large function finding
                if fn_len > 60:
                    snippet = self._get_snippet(lines, start_line, min(start_line + 6, len(lines)))
                    findings.append(FindingResult(
                        severity="warning",
                        title=f"Function '{fn_name}' Exceeds 60 Lines of Code ({fn_len} LOC)",
                        description=f"Function '{fn_name}' spans {fn_len} continuous lines. Functions over 60 LOC typically manage too many tasks.",
                        file_path=rel_path,
                        line_start=start_line,
                        line_end=end_line,
                        code_snippet=snippet,
                        impact="Harder to unit test in isolation and review for side effects.",
                        recommendation="Split function into dedicated single-responsibility sub-routines."
                    ))

    def _analyze_generic_code_file(self, lines: List[str], rel_path: str, findings: List[FindingResult], complexities: List[int]):
        # Simple heuristic scanner for JS, TS, Go, Rust, Java
        branch_regex = re.compile(r"\b(if|else if|for|while|catch|switch|case|\?\?|&&|\|\|)\b")
        fn_start_regex = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function\s+([a-zA-Z0-9_$]+)|const\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>|def\s+([a-zA-Z0-9_$]+)|func\s+(?:\([^)]+\)\s*)?([a-zA-Z0-9_$]+))")

        current_fn = None
        current_fn_start = 0
        current_fn_complexity = 1
        indent_stack = 0

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("#"):
                continue

            # Check deep nesting (> 4 levels)
            indent = len(line) - len(line.lstrip(" "))
            tabs = line.count("\t") * 4
            effective_indent = (indent + tabs) // 4
            if effective_indent >= 5:
                if len(findings) < 15 and not any(f.file_path == rel_path and f.line_start == i for f in findings):
                    snippet = self._get_snippet(lines, max(1, i - 1), min(len(lines), i + 1))
                    findings.append(FindingResult(
                        severity="info",
                        title=f"Deep Call Nesting ({effective_indent} levels) in '{rel_path}'",
                        description=f"Deeply indented code structure ({effective_indent} levels deep) detected at line {i}.",
                        file_path=rel_path,
                        line_start=i,
                        line_end=i,
                        code_snippet=snippet,
                        impact="Reduces readability and increases likelihood of state management oversights.",
                        recommendation="Use early return guard clauses to flatten the indentation hierarchy."
                    ))

            # Detect function headers
            match = fn_start_regex.search(line)
            if match:
                if current_fn and (i - current_fn_start) > 60:
                    fn_len = i - current_fn_start
                    snippet = self._get_snippet(lines, current_fn_start, min(current_fn_start + 6, len(lines)))
                    findings.append(FindingResult(
                        severity="warning",
                        title=f"Large Function Exceeds 60 Lines ({fn_len} LOC)",
                        description=f"Function starting at line {current_fn_start} spans {fn_len} lines.",
                        file_path=rel_path,
                        line_start=current_fn_start,
                        line_end=i,
                        code_snippet=snippet,
                        impact="High cognitive load during code audits.",
                        recommendation="Extract sub-logic into separate functions."
                    ))

                current_fn = match.group(1) or match.group(2) or match.group(3) or match.group(4) or "anonymous"
                current_fn_start = i
                complexities.append(current_fn_complexity)
                current_fn_complexity = 1

            # Count branching
            if branch_regex.search(line):
                current_fn_complexity += 1

        if current_fn:
            complexities.append(current_fn_complexity)
            fn_len = len(lines) - current_fn_start + 1
            if fn_len > 60:
                snippet = self._get_snippet(lines, current_fn_start, min(current_fn_start + 6, len(lines)))
                findings.append(FindingResult(
                    severity="warning",
                    title=f"Large Function Exceeds 60 Lines ({fn_len} LOC)",
                    description=f"Function '{current_fn}' starting at line {current_fn_start} spans {fn_len} lines.",
                    file_path=rel_path,
                    line_start=current_fn_start,
                    line_end=len(lines),
                    code_snippet=snippet,
                    impact="High cognitive load during code audits.",
                    recommendation="Extract sub-logic into separate functions."
                ))

    def _get_snippet(self, lines: List[str], start: int, end: int) -> str:
        snippet_lines = []
        for line_num in range(max(1, start), min(len(lines) + 1, end + 1)):
            snippet_lines.append(f"{line_num:4d} | {lines[line_num - 1].rstrip()}")
        return "\n".join(snippet_lines)
