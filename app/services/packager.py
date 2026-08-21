import os
from pathlib import Path
from typing import Dict, Any, List

IGNORE_DIRS = {
    ".git", "node_modules", "dist", "build", "vendor", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "coverage", ".next", ".nuxt", "target"
}

MANIFEST_FILENAMES = {
    "package.json", "pyproject.toml", "requirements.txt", "Pipfile",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "composer.json"
}

ENTRYPOINT_CANDIDATES = {
    "main.py", "app.py", "server.py", "index.py", "wsgi.py", "asgi.py",
    "index.js", "app.js", "server.js", "main.js",
    "index.ts", "app.ts", "server.ts", "main.ts",
    "main.go", "main.rs", "App.java", "Main.java"
}

MAX_TOTAL_PAYLOAD_BYTES = 150 * 1024  # 150 KB budget

def build_directory_tree(repo_dir: Path, max_depth: int = 4) -> str:
    """Constructs a clean, indented text representation of the file tree."""
    tree_lines = [f"{repo_dir.name}/"]

    def _walk(current_dir: Path, prefix: str, depth: int):
        if depth > max_depth:
            tree_lines.append(f"{prefix}... (depth limit reached)")
            return

        try:
            entries = sorted(list(current_dir.iterdir()), key=lambda e: (not e.is_dir(), e.name.lower()))
        except Exception:
            return

        # Filter ignored dirs
        entries = [e for e in entries if e.name not in IGNORE_DIRS]

        for i, entry in enumerate(entries):
            is_last = (i == len(entries) - 1)
            connector = "└── " if is_last else "├── "
            child_prefix = "    " if is_last else "│   "

            if entry.is_dir():
                tree_lines.append(f"{prefix}{connector}{entry.name}/")
                _walk(entry, prefix + child_prefix, depth + 1)
            else:
                tree_lines.append(f"{prefix}{connector}{entry.name}")

    _walk(repo_dir, "", 1)
    return "\n".join(tree_lines[:250])  # Cap at 250 tree lines

def package_repository_context(repo_dir: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Packages repo tree, manifests, and top entrypoint files into a single context payload
    strictly bounded to stay under Gemini token limits.
    """
    tree_str = build_directory_tree(repo_dir)
    manifests: Dict[str, str] = {}
    entrypoints: Dict[str, str] = {}
    readme_content = ""

    bytes_budget_remaining = MAX_TOTAL_PAYLOAD_BYTES - len(tree_str.encode("utf-8"))

    # 1. Read README if available
    for readme_name in ["README.md", "README.rst", "README.txt", "readme.md"]:
        readme_path = repo_dir / readme_name
        if readme_path.exists():
            try:
                content = readme_path.read_text(encoding="utf-8", errors="ignore")[:4000]
                readme_content = content
                bytes_budget_remaining -= len(readme_content.encode("utf-8"))
            except Exception:
                pass
            break

    # 2. Extract manifests and entrypoints
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file in files:
            file_path = Path(root) / file
            rel_path = str(file_path.relative_to(repo_dir)).replace("\\", "/")

            if file in MANIFEST_FILENAMES and bytes_budget_remaining > 0:
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")[:4000]
                    manifests[rel_path] = content
                    bytes_budget_remaining -= len(content.encode("utf-8"))
                except Exception:
                    pass

            elif file in ENTRYPOINT_CANDIDATES and bytes_budget_remaining > 0:
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")[:5000]
                    entrypoints[rel_path] = content
                    bytes_budget_remaining -= len(content.encode("utf-8"))
                except Exception:
                    pass

    return {
        "repo_name": f"{metadata.get('owner', '')}/{metadata.get('repo_name', '')}",
        "primary_language": metadata.get("primary_language", "Unknown"),
        "description": metadata.get("description", ""),
        "tree": tree_str,
        "readme_snippet": readme_content,
        "manifests": manifests,
        "entrypoints": entrypoints,
    }
