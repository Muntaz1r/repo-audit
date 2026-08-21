from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class FindingResult(BaseModel):
    severity: str = Field(..., description="critical, warning, or info")
    title: str
    description: str
    file_path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    code_snippet: Optional[str] = None
    impact: Optional[str] = None
    recommendation: Optional[str] = None

class PillarResult(BaseModel):
    pillar_key: str
    score: int
    status: str = "PASS"  # PASS, WARN, FAIL, PREVIEW
    metrics_json: Dict[str, Any] = Field(default_factory=dict)
    findings: List[FindingResult] = Field(default_factory=list)

class BasePillarAnalyzer(ABC):
    @property
    @abstractmethod
    def pillar_key(self) -> str:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    async def analyze(self, repo_dir: Path, metadata: Dict[str, Any]) -> PillarResult:
        """Run analysis on cloned repository directory and return structured PillarResult."""
        pass
