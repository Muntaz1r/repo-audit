import uuid
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Audit, AuditPillar, AuditFinding, AuditLog
from app.services.cloner import fetch_github_metadata, shallow_clone_repo, cleanup_workspace, parse_github_url
from app.services.packager import package_repository_context
from app.services.analyzers.code_eval import CodeEvaluationAnalyzer
from app.services.analyzers.semantic import SemanticAnalyzer
from app.services.analyzers.security import SecurityAnalyzer
from app.services.analyzers.docs import DocumentationAnalyzer
from app.services.analyzers.prod_readiness import ProdReadinessAnalyzer

def generate_audit_id() -> str:
    return f"aud_{uuid.uuid4().hex[:10]}"

def log_step(db: Session, audit_id: str, step: str, message: str):
    log_entry = AuditLog(
        audit_id=audit_id,
        step=step,
        message=message,
        created_at=datetime.now(timezone.utc)
    )
    db.add(log_entry)
    db.commit()

async def run_audit_pipeline(audit_id: str, repo_url: str):
    """
    Main asynchronous background worker orchestrating all 5 pillars with adversarial protections:
    1. Validation & GitHub Metadata Fetch (with 403 rate-limit fallback)
    2. Sandboxed Shallow Clone (with empty repo guard)
    3. Pillar 01: Semantic Analysis (Gemini Flash AI / Heuristic + 30s timeout guard)
    4. Pillar 02: Code Evaluation Engine (Radon & AST + 30s timeout guard)
    5. Pillar 03: Security & Vulnerability Scanner (Null-byte filter + 30s timeout guard)
    6. Pillar 04: Documentation Quality Analysis (Polyglot AST + 30s timeout guard)
    7. Pillar 05: Production Readiness Analyzer (Non-empty config check + 30s timeout guard)
    8. Composite 5-pillar weighted scoring with Grade F Hard Ceiling on critical leaks
    9. Database persistence
    10. Workspace teardown
    """
    db = SessionLocal()
    try:
        audit = db.query(Audit).filter(Audit.id == audit_id).first()
        if not audit:
            return

        # STAGE 1: METADATA
        audit.status = "CLONING"
        db.commit()
        log_step(db, audit_id, "METADATA_FETCH", f"Resolving repository metadata for '{repo_url}'...")

        owner, repo_name = parse_github_url(repo_url)
        meta = await fetch_github_metadata(owner, repo_name)
        
        audit.owner = meta["owner"]
        audit.repo_name = meta["repo_name"]
        audit.default_branch = meta["default_branch"]
        audit.stars_count = meta["stars_count"]
        audit.primary_language = meta["primary_language"]
        db.commit()
        log_step(db, audit_id, "METADATA_RESOLVED", f"Metadata resolved: {meta['stars_count']} stars, default branch '{meta['default_branch']}'.")

        # STAGE 2: SHALLOW CLONE
        log_step(db, audit_id, "CLONE_START", f"Shallow cloning '{owner}/{repo_name}' (--depth 1)...")
        repo_dir = shallow_clone_repo(repo_url, audit_id)
        log_step(db, audit_id, "CLONE_COMPLETE", "Cloned into ephemeral workspace sandbox.")

        # STAGE 3: RUN ALL 5 ANALYZERS CONCURRENTLY WITH PER-PILLAR TIMEOUTS
        audit.status = "ANALYZING"
        db.commit()

        # Pillar 01: Semantic Analysis (Multi-Provider Cascade)
        log_step(db, audit_id, "ANALYZE_SEMANTIC_START", "Running Pillar 01: Semantic Analysis Engine (Gemini / Groq)...")
        semantic_analyzer = SemanticAnalyzer()
        try:
            semantic_result = await asyncio.wait_for(semantic_analyzer.analyze(repo_dir, meta), timeout=45.0)
        except asyncio.TimeoutError:
            pkg = package_repository_context(repo_dir, meta)
            semantic_result = semantic_analyzer._heuristic_analysis(pkg, meta)

        pillar_01 = AuditPillar(
            audit_id=audit_id,
            pillar_key=semantic_result.pillar_key,
            score=semantic_result.score,
            status=semantic_result.status,
            metrics_json=semantic_result.metrics_json,
        )
        db.add(pillar_01)
        for f in semantic_result.findings:
            db.add(AuditFinding(
                audit_id=audit_id,
                pillar_key=semantic_result.pillar_key,
                severity=f.severity,
                title=f.title,
                description=f.description,
                file_path=f.file_path,
                line_start=f.line_start,
                line_end=f.line_end,
                code_snippet=f.code_snippet,
                impact=f.impact,
                recommendation=f.recommendation,
            ))
        log_step(db, audit_id, "ANALYZE_SEMANTIC_DONE", f"Semantic Analysis complete: Score {semantic_result.score}/100 ({semantic_result.metrics_json.get('architecture_type', 'Modular')}).")

        # Pillar 02: Code Evaluation
        log_step(db, audit_id, "ANALYZE_CODE_EVAL_START", "Running Pillar 02: Code Evaluation Engine...")
        code_evaluator = CodeEvaluationAnalyzer()
        code_result = await asyncio.wait_for(code_evaluator.analyze(repo_dir, meta), timeout=30.0)

        pillar_02 = AuditPillar(
            audit_id=audit_id,
            pillar_key=code_result.pillar_key,
            score=code_result.score,
            status=code_result.status,
            metrics_json=code_result.metrics_json,
        )
        db.add(pillar_02)
        for f in code_result.findings:
            db.add(AuditFinding(
                audit_id=audit_id,
                pillar_key=code_result.pillar_key,
                severity=f.severity,
                title=f.title,
                description=f.description,
                file_path=f.file_path,
                line_start=f.line_start,
                line_end=f.line_end,
                code_snippet=f.code_snippet,
                impact=f.impact,
                recommendation=f.recommendation,
            ))
        log_step(db, audit_id, "ANALYZE_CODE_EVAL_DONE", f"Code Evaluation complete: Score {code_result.score}/100 with {len(code_result.findings)} findings.")

        # Pillar 03: Security & Vulnerability Scanning
        log_step(db, audit_id, "ANALYZE_SECURITY_START", "Running Pillar 03: Security & Vulnerability Scanner...")
        security_analyzer = SecurityAnalyzer()
        security_result = await asyncio.wait_for(security_analyzer.analyze(repo_dir, meta), timeout=30.0)

        pillar_03 = AuditPillar(
            audit_id=audit_id,
            pillar_key=security_result.pillar_key,
            score=security_result.score,
            status=security_result.status,
            metrics_json=security_result.metrics_json,
        )
        db.add(pillar_03)
        for f in security_result.findings:
            db.add(AuditFinding(
                audit_id=audit_id,
                pillar_key=security_result.pillar_key,
                severity=f.severity,
                title=f.title,
                description=f.description,
                file_path=f.file_path,
                line_start=f.line_start,
                line_end=f.line_end,
                code_snippet=f.code_snippet,
                impact=f.impact,
                recommendation=f.recommendation,
            ))
        log_step(db, audit_id, "ANALYZE_SECURITY_DONE", f"Security Scan complete: Score {security_result.score}/100 with {len(security_result.findings)} security findings.")

        # Pillar 04: Documentation Quality Analysis
        log_step(db, audit_id, "ANALYZE_DOCS_START", "Running Pillar 04: Documentation Quality Analyzer...")
        docs_analyzer = DocumentationAnalyzer()
        docs_result = await asyncio.wait_for(docs_analyzer.analyze(repo_dir, meta), timeout=30.0)

        pillar_04 = AuditPillar(
            audit_id=audit_id,
            pillar_key=docs_result.pillar_key,
            score=docs_result.score,
            status=docs_result.status,
            metrics_json=docs_result.metrics_json,
        )
        db.add(pillar_04)
        for f in docs_result.findings:
            db.add(AuditFinding(
                audit_id=audit_id,
                pillar_key=docs_result.pillar_key,
                severity=f.severity,
                title=f.title,
                description=f.description,
                file_path=f.file_path,
                line_start=f.line_start,
                line_end=f.line_end,
                code_snippet=f.code_snippet,
                impact=f.impact,
                recommendation=f.recommendation,
            ))
        log_step(db, audit_id, "ANALYZE_DOCS_DONE", f"Documentation Analysis complete: Score {docs_result.score}/100 with {len(docs_result.findings)} documentation findings.")

        # Pillar 05: Production Readiness Analysis
        log_step(db, audit_id, "ANALYZE_PROD_START", "Running Pillar 05: Production Readiness Analyzer...")
        prod_analyzer = ProdReadinessAnalyzer()
        prod_result = await asyncio.wait_for(prod_analyzer.analyze(repo_dir, meta), timeout=30.0)

        pillar_05 = AuditPillar(
            audit_id=audit_id,
            pillar_key=prod_result.pillar_key,
            score=prod_result.score,
            status=prod_result.status,
            metrics_json=prod_result.metrics_json,
        )
        db.add(pillar_05)
        for f in prod_result.findings:
            db.add(AuditFinding(
                audit_id=audit_id,
                pillar_key=prod_result.pillar_key,
                severity=f.severity,
                title=f.title,
                description=f.description,
                file_path=f.file_path,
                line_start=f.line_start,
                line_end=f.line_end,
                code_snippet=f.code_snippet,
                impact=f.impact,
                recommendation=f.recommendation,
            ))
        log_step(db, audit_id, "ANALYZE_PROD_DONE", f"Production Readiness complete: Score {prod_result.score}/100 with {len(prod_result.findings)} findings.")

        # STAGE 4: COMPOSITE 5-PILLAR VERDICT SYNTHESIS (WITH ADVERSARIAL HARD CEILING)
        # Weights: Code Eval (30%), Security (30%), Prod Readiness (15%), Docs (15%), Semantic (10%)
        overall_score = int(
            (code_result.score * 0.30) +
            (security_result.score * 0.30) +
            (prod_result.score * 0.15) +
            (docs_result.score * 0.15) +
            (semantic_result.score * 0.10)
        )
        
        # Determine initial grade
        if overall_score >= 90:
            grade = "A"
            verdict_text = f"Exceptional {semantic_result.metrics_json.get('architecture_type', 'codebase')} demonstrating production-grade maturity, comprehensive test health, robust security, and thorough documentation."
        elif overall_score >= 80:
            grade = "B"
            verdict_text = f"High quality {semantic_result.metrics_json.get('architecture_type', 'codebase')} meeting industry production conventions. Minor maintainability or configuration improvements recommended."
        elif overall_score >= 70:
            grade = "C"
            verdict_text = f"Moderate maintainability or operational friction in {semantic_result.metrics_json.get('architecture_type', 'codebase')}. Review flagged items before production deployment."
        elif overall_score >= 60:
            grade = "D"
            verdict_text = f"Notable risks detected in code hygiene, documentation, or operational readiness for {semantic_result.metrics_json.get('architecture_type', 'this repository')}."
        else:
            grade = "F"
            verdict_text = "Critical production risks, vulnerabilities, or complete absence of automated test verification."

        # ADVERSARIAL HARD CEILING: Any critical security finding caps score at 45 and forces Grade F
        crit_sec = [f for f in security_result.findings if f.severity == "critical"]
        if crit_sec:
            overall_score = min(overall_score, 45)
            grade = "F"
            verdict_text = f"CRITICAL SECURITY BLOCKER: {len(crit_sec)} critical exposed secret/vulnerability issue(s) detected. Immediate remediation required prior to any production deployment."

        audit.overall_score = overall_score
        audit.overall_grade = grade
        audit.verdict_summary = verdict_text
        audit.status = "COMPLETED"
        audit.completed_at = datetime.now(timezone.utc)
        db.commit()

        log_step(db, audit_id, "SYNTHESIS_DONE", f"Audit finalized: Grade {grade} ({overall_score}/100).")

    except Exception as e:
        if db:
            audit = db.query(Audit).filter(Audit.id == audit_id).first()
            if audit:
                audit.status = "FAILED"
                audit.error_message = str(e)
                audit.completed_at = datetime.now(timezone.utc)
                db.commit()
                log_step(db, audit_id, "PIPELINE_ERROR", f"Audit failed: {str(e)}")
    finally:
        cleanup_workspace(audit_id)
        db.close()
