import pytest
from pathlib import Path
from app.services.packager import package_repository_context, build_directory_tree
from app.services.analyzers.semantic import SemanticAnalyzer

def test_build_directory_tree(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')")
    (tmp_path / "package.json").write_text('{"name": "test"}')

    tree = build_directory_tree(tmp_path)
    assert "src/" in tree
    assert "package.json" in tree

def test_package_repository_context(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Test Repo\nThis is a test application.")
    (tmp_path / "package.json").write_text('{"name": "test-repo", "dependencies": {}}')
    (tmp_path / "index.js").write_text("console.log('started');")

    pkg = package_repository_context(tmp_path, {
        "owner": "testorg",
        "repo_name": "test-repo",
        "primary_language": "JavaScript",
        "description": "A sample testing repository."
    })

    assert pkg["repo_name"] == "testorg/test-repo"
    assert "Test Repo" in pkg["readme_snippet"]
    assert "package.json" in pkg["manifests"]
    assert "index.js" in pkg["entrypoints"]

def test_semantic_analyzer_heuristic_fallback(tmp_path: Path):
    (tmp_path / "routes").mkdir()
    (tmp_path / "routes" / "api.js").write_text("module.exports = {};")
    (tmp_path / "package.json").write_text('{"name": "my-express-app"}')

    analyzer = SemanticAnalyzer()
    pkg = package_repository_context(tmp_path, {
        "owner": "test",
        "repo_name": "my-express-app",
        "primary_language": "JavaScript"
    })
    result = analyzer._heuristic_analysis(pkg, {
        "owner": "test",
        "repo_name": "my-express-app",
        "primary_language": "JavaScript"
    })

    assert result.pillar_key == "semantic"
    assert result.score >= 80
    assert result.status == "PASS"
    assert "architecture_type" in result.metrics_json
    assert "purpose_summary" in result.metrics_json
    assert len(result.metrics_json["key_modules"]) >= 1

def test_semantic_analyzer_build_result():
    analyzer = SemanticAnalyzer()
    mock_data = {
        "architecture_type": "MVC Web Framework",
        "purpose_summary": "High performance unopinionated web routing engine.",
        "design_patterns": ["Middleware Pipeline", "Router Tree"],
        "key_modules": [
            {"name": "Router", "path": "lib/router.js", "purpose": "Handles HTTP path matching"}
        ],
        "data_flow_summary": "Requests pass through middleware stack to route handlers.",
        "architectural_strengths": ["Clear modular separation"],
        "architectural_risks": ["Circular dependency between request and response prototypes"]
    }

    # Test Gemini engine
    res_gemini = analyzer._build_result(mock_data, engine="Gemini 2.5 Flash (Live AI)")
    assert res_gemini.pillar_key == "semantic"
    assert res_gemini.score < 100  # Penalty for architectural risk
    assert res_gemini.metrics_json["engine"] == "Gemini 2.5 Flash (Live AI)"
    assert len(res_gemini.findings) == 1

    # Test Groq engine
    res_groq = analyzer._build_result(mock_data, engine="Groq Llama-3.3-70B (Live AI)")
    assert res_groq.pillar_key == "semantic"
    assert res_groq.metrics_json["engine"] == "Groq Llama-3.3-70B (Live AI)"

def test_semantic_analyzer_build_result_null_safety():
    """Verify null-safety when LLM returns null for array or string fields."""
    analyzer = SemanticAnalyzer()
    null_data = {
        "architecture_type": None,
        "purpose_summary": None,
        "design_patterns": None,
        "key_modules": None,
        "data_flow_summary": None,
        "architectural_strengths": None,
        "architectural_risks": None
    }
    result = analyzer._build_result(null_data, engine="Groq llama-3.3-70b-versatile (Live AI)")
    assert result.pillar_key == "semantic"
    assert result.score == 95
    assert result.status == "PASS"
    assert result.metrics_json["architecture_type"] == "Modular Software"
    assert result.metrics_json["design_patterns"] == []
    assert result.metrics_json["key_modules"] == []
    assert len(result.findings) == 0

def test_semantic_analyzer_dict_risks_handling():
    """Verify handling when LLM returns risks as array of objects instead of strings."""
    analyzer = SemanticAnalyzer()
    data = {
        "architecture_type": "CLI Utility",
        "architectural_risks": [
            {"risk": "Tight coupling between CLI flags and business logic", "severity": "medium"}
        ]
    }
    result = analyzer._build_result(data, engine="Gemini 2.5 Flash (Live AI)")
    assert result.score == 90
    assert len(result.findings) == 1
    assert "Tight coupling" in result.findings[0].description
