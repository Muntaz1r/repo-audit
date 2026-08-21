from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.database import Base

def utc_now():
    return datetime.now(timezone.utc)

class Audit(Base):
    __tablename__ = "audits"

    id = Column(String(36), primary_key=True, index=True)
    repo_url = Column(Text, nullable=False)
    owner = Column(String(120), nullable=False)
    repo_name = Column(String(120), nullable=False)
    default_branch = Column(String(80), default="main")
    stars_count = Column(Integer, default=0)
    primary_language = Column(String(50), nullable=True)
    status = Column(String(30), nullable=False, default="QUEUED", index=True)  # QUEUED, CLONING, ANALYZING, COMPLETED, FAILED
    error_message = Column(Text, nullable=True)
    overall_score = Column(Integer, nullable=True)
    overall_grade = Column(String(2), nullable=True)  # A, B, C, D, F
    verdict_summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    pillars = relationship("AuditPillar", back_populates="audit", cascade="all, delete-orphan")
    findings = relationship("AuditFinding", back_populates="audit", cascade="all, delete-orphan")
    logs = relationship("AuditLog", back_populates="audit", cascade="all, delete-orphan")


class AuditPillar(Base):
    __tablename__ = "audit_pillars"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(36), ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True)
    pillar_key = Column(String(40), nullable=False)  # semantic, code_eval, security, docs, prod_readiness
    score = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="PASS")  # PASS, WARN, FAIL, PREVIEW
    metrics_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    audit = relationship("Audit", back_populates="pillars")


class AuditFinding(Base):
    __tablename__ = "audit_findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(36), ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True)
    pillar_key = Column(String(40), nullable=False, index=True)
    severity = Column(String(20), nullable=False, index=True)  # critical, warning, info
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    file_path = Column(Text, nullable=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    code_snippet = Column(Text, nullable=True)
    impact = Column(Text, nullable=True)
    recommendation = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    audit = relationship("Audit", back_populates="findings")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(36), ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True)
    step = Column(String(60), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)

    audit = relationship("Audit", back_populates="logs")
