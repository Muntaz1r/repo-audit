import pytest
from pathlib import Path
from app.services.analyzers.docs import DocumentationAnalyzer

@pytest.mark.asyncio
async def test_docs_analyzer_complete_repo(tmp_path: Path):
    readme_text = """# My Cool Project
## Overview
This is a comprehensive open-source repository designed to provide high performance web utilities and modular tools for developers building scalable backend services.

## Installation
To install the package, simply use your preferred package manager:
```bash
pip install cool-project
```

## Usage
Import the package and initialize your application context:
```python
from cool_project import App
app = App()
app.run()
```

## Configuration
Set the following environment variables in your local `.env`:
- `CONFIG_VAR`: Sets the runtime mode.
- `PORT`: Server listening port (default 8000).

## Contributing
We welcome community pull requests and bug reports. Please see our guidelines before submitting.

## License
MIT License - see LICENSE file for details.
"""
    (tmp_path / "README.md").write_text(readme_text)
    (tmp_path / "LICENSE").write_text("MIT License (c) 2026")
    
    py_code = """
def public_func():
    \"\"\"This function does something useful.\"\"\"
    return 42

class CoolClass:
    \"\"\"Cool class representation.\"\"\"
    pass
"""
    (tmp_path / "app.py").write_text(py_code)

    analyzer = DocumentationAnalyzer()
    result = await analyzer.analyze(tmp_path, {"owner": "test", "repo_name": "complete-docs"})

    assert result.pillar_key == "docs"
    assert result.score >= 90
    assert result.status == "PASS"
    assert result.metrics_json["has_readme"] is True
    assert result.metrics_json["has_license"] is True
    assert result.metrics_json["readme_sections"]["installation"] is True
    assert result.metrics_json["readme_sections"]["usage"] is True
    assert result.metrics_json["docstring_coverage_pct"] == 100.0
    assert len(result.findings) == 0

@pytest.mark.asyncio
async def test_docs_analyzer_missing_readme_and_license(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.js").write_text("function undocumented() { return 1; }")

    analyzer = DocumentationAnalyzer()
    result = await analyzer.analyze(tmp_path, {"owner": "test", "repo_name": "no-docs"})

    assert result.pillar_key == "docs"
    assert result.score < 60
    assert result.status in ["WARN", "FAIL"]
    assert result.metrics_json["has_readme"] is False
    assert result.metrics_json["has_license"] is False
    assert len(result.findings) >= 2

    titles = [f.title for f in result.findings]
    assert any("Missing Repository README" in t for t in titles)
    assert any("Missing Software License" in t for t in titles)

@pytest.mark.asyncio
async def test_docs_analyzer_polyglot_languages(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Polyglot Project\n## Overview\nTest\n## Installation\nTest\n## Usage\nTest\n## License\nMIT")
    (tmp_path / "LICENSE").write_text("MIT License")
    
    # Go file
    go_code = """package main
// ExportedFunction calculates sum
func ExportedFunction() int { return 1 }
"""
    (tmp_path / "main.go").write_text(go_code)

    # Rust file
    rs_code = """
/// Public struct representation
pub struct ServerConfig;
"""
    (tmp_path / "lib.rs").write_text(rs_code)

    analyzer = DocumentationAnalyzer()
    result = await analyzer.analyze(tmp_path, {"owner": "test", "repo_name": "polyglot"})

    assert result.pillar_key == "docs"
    assert result.metrics_json["total_symbols_scanned"] == 2
    assert result.metrics_json["documented_symbols"] == 2
    assert result.metrics_json["docstring_coverage_pct"] == 100.0
