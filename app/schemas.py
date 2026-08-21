from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict, Field

class AuditCreateRequest(BaseModel):
    repo_url: str = Field(..., description="Public GitHub repository URL (e.g. https://github.com/expressjs/express)")

class AuditFindingSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    pillar_key: str
    severity: str
    title: str
    description: str
    file_path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    code_snippet: Optional[str] = None
    impact: Optional[str] = None
    recommendation: Optional[str] = None
    created_at: Optional[datetime] = None

class AuditPillarSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pillar_key: str
    score: int
    status: str
    metrics_json: Dict[str, Any] = Field(default_factory=dict)
    findings: List[AuditFindingSchema] = Field(default_factory=list)

class AuditLogSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step: str
    message: str
    created_at: datetime

class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    repo_url: str
    owner: str
    repo_name: str
    default_branch: str
    stars_count: int
    primary_language: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    overall_score: Optional[int] = None
    overall_grade: Optional[str] = None
    verdict_summary: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    pillars: List[AuditPillarSchema] = Field(default_factory=list)
    findings: List[AuditFindingSchema] = Field(default_factory=list)
    logs: List[AuditLogSchema] = Field(default_factory=list)

class AuditSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    repo_url: str
    owner: str
    repo_name: str
    status: str
    overall_score: Optional[int] = None
    overall_grade: Optional[str] = None
    created_at: datetime
