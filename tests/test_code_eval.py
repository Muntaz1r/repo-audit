import pytest
import shutil
from pathlib import Path
from app.services.analyzers.code_eval import CodeEvaluationAnalyzer

@pytest.mark.asyncio
async def test_code_eval_analyzer(tmp_path: Path):
    # Setup mock repository files
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    
    # 1. Standard python file with moderate complexity
    py_file = src_dir / "calculator.py"
    py_file.write_text("""
def calculate(a, b, op):
    if op == '+':
        return a + b
    elif op == '-':
        return a - b
    elif op == '*':
        return a * b
    elif op == '/':
        if b != 0:
            return a / b
        else:
            return 0
    return None
""")

    # 2. Test file
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_file = test_dir / "test_calc.py"
    test_file.write_text("""
from src.calculator import calculate

def test_add():
    assert calculate(2, 3, '+') == 5
""")

    analyzer = CodeEvaluationAnalyzer()
    result = await analyzer.analyze(tmp_path, {"primary_language": "Python"})

    assert result.pillar_key == "code_eval"
    assert result.score > 70
    assert result.metrics_json["total_code_files"] == 2
    assert result.metrics_json["test_files_count"] == 1
    assert result.metrics_json["source_files_count"] == 1
    assert result.metrics_json["test_to_source_ratio"] == 1.0

@pytest.mark.asyncio
async def test_code_eval_smells(tmp_path: Path):
    # Setup repository with large function smell
    src_dir = tmp_path / "lib"
    src_dir.mkdir()
    big_file = src_dir / "big_module.js"

    # Generate 70-line function
    lines = ["function largeHandler(req, res) {"]
    for i in range(70):
        lines.append(f"  const step{i} = {i};")
    lines.append("  return res.send('ok');")
    lines.append("}")
    big_file.write_text("\n".join(lines))

    analyzer = CodeEvaluationAnalyzer()
    result = await analyzer.analyze(tmp_path, {"primary_language": "JavaScript"})

    assert any("Large Function" in f.title for f in result.findings)
    assert result.score < 100
