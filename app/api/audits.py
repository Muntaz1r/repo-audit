from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Audit, AuditPillar, AuditFinding, AuditLog
from app.schemas import AuditCreateRequest, AuditResponse, AuditSummary
from app.services.cloner import parse_github_url
from app.services.orchestrator import generate_audit_id, run_audit_pipeline, log_step

router = APIRouter(prefix="/api/audits", tags=["Audits"])

@router.post("", response_model=AuditResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_audit(
    request: AuditCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Submits a public GitHub URL for auditing.
    Immediately returns 202 Accepted with audit_id and processes in the background.
    """
    try:
        owner, repo_name = parse_github_url(request.repo_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    audit_id = generate_audit_id()
    new_audit = Audit(
        id=audit_id,
        repo_url=request.repo_url.strip(),
        owner=owner,
        repo_name=repo_name,
        status="QUEUED"
    )
    db.add(new_audit)
    db.commit()
    db.refresh(new_audit)

    log_step(db, audit_id, "JOB_ENQUEUED", f"Job enqueued for '{owner}/{repo_name}'.")

    # Dispatch asynchronous background task
    background_tasks.add_task(run_audit_pipeline, audit_id, request.repo_url.strip())

    return new_audit

@router.get("/{audit_id}", response_model=AuditResponse)
def get_audit(audit_id: str, db: Session = Depends(get_db)):
    """Fetches audit status, telemetry logs, pillar results, and findings."""
    audit = db.query(Audit).filter(Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit job not found")
    return audit

@router.get("/{audit_id}/export")
def export_audit(audit_id: str, format: str = "markdown", db: Session = Depends(get_db)):
    """Exports the completed audit report as structured Markdown or JSON."""
    from fastapi.responses import Response, JSONResponse

    audit = db.query(Audit).filter(Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit job not found")

    if format.lower() == "json":
        data = {
            "audit_id": audit.id,
            "repo_url": audit.repo_url,
            "owner": audit.owner,
            "repo_name": audit.repo_name,
            "stars_count": audit.stars_count,
            "overall_score": audit.overall_score,
            "overall_grade": audit.overall_grade,
            "verdict_summary": audit.verdict_summary,
            "created_at": audit.created_at.isoformat() if audit.created_at else None,
            "completed_at": audit.completed_at.isoformat() if audit.completed_at else None,
            "pillars": [
                {
                    "pillar_key": p.pillar_key,
                    "score": p.score,
                    "status": p.status,
                    "metrics": p.metrics_json
                } for p in audit.pillars
            ],
            "findings": [
                {
                    "pillar_key": f.pillar_key,
                    "severity": f.severity,
                    "title": f.title,
                    "description": f.description,
                    "file_path": f.file_path,
                    "line_start": f.line_start,
                    "impact": f.impact,
                    "recommendation": f.recommendation
                } for f in audit.findings
            ]
        }
        return JSONResponse(
            content=data,
            headers={"Content-Disposition": f"attachment; filename=repoaudit_{audit.repo_name}_{audit.id}.json"}
        )

    # Markdown Export
    md = [
        f"# RepoAudit Report — {audit.owner}/{audit.repo_name}",
        f"**Repository URL**: {audit.repo_url}  ",
        f"**Audit ID**: `{audit.id}`  ",
        f"**Overall Score**: **{audit.overall_score} / 100** (Grade {audit.overall_grade})  ",
        f"**Date**: {audit.created_at.strftime('%Y-%m-%d %H:%M:%S UTC') if audit.created_at else 'N/A'}\n",
        "## Executive Verdict Summary",
        f"> {audit.verdict_summary}\n",
        "## 5-Pillar Scorecard",
        "| Pillar | Score | Status | Key Insight |",
        "| :--- | :--- | :--- | :--- |"
    ]

    for p in audit.pillars:
        insight = p.metrics_json.get("purpose_summary") or p.metrics_json.get("secret_scanner_status") or f"{p.status} ({p.score}/100)"
        if len(str(insight)) > 60:
            insight = str(insight)[:57] + "..."
        md.append(f"| **{p.pillar_key.upper()}** | {p.score}/100 | `{p.status}` | {insight} |")

    md.append("\n## Detailed Findings")
    if not audit.findings:
        md.append("_No critical risks or maintainability issues flagged._\n")
    else:
        for idx, f in enumerate(audit.findings, 1):
            md.append(f"### {idx}. [{f.severity.upper()}] {f.title}")
            if f.file_path:
                md.append(f"**Location**: `{f.file_path}{f':L{f.line_start}' if f.line_start else ''}`  ")
            md.append(f"**Description**: {f.description}  ")
            if f.impact:
                md.append(f"**Reviewer Impact**: {f.impact}  ")
            if f.recommendation:
                md.append(f"**Recommended Fix**: {f.recommendation}  ")
            if f.code_snippet:
                md.append(f"```\n{f.code_snippet}\n```")
            md.append("")

    content = "\n".join(md)
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=repoaudit_{audit.repo_name}_{audit.id}.md"}
    )
