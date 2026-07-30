from typing import List, Optional
from pydantic import BaseModel


class Clause(BaseModel):
    id: str
    text: str


class ClauseAnalysis(BaseModel):
    clause_id: str
    classification: str  # "standard" | "risky" | "missing" | "non_standard"
    risk_level: str  # "low" | "medium" | "high"
    rationale: str
    redline_suggestion: Optional[str] = None


class CompanyContext(BaseModel):
    company_name: Optional[str] = None
    summary: Optional[str] = None
    sources: List[str] = []


class AnalyzeResponse(BaseModel):
    session_id: str
    filename: str
    is_contract: bool
    document_type_reason: Optional[str] = None
    company_context: CompanyContext
    clauses: List[Clause]
    clause_analysis: List[ClauseAnalysis]
    risk_summary: str
    review_status: str  # "pending" | "rejected"


class ReviewRequest(BaseModel):
    session_id: str
    decision: str  # "approve" | "request_changes"
    notes: Optional[str] = None


class ReviewResponse(BaseModel):
    session_id: str
    review_status: str  # "approved" | "changes_requested"
    clause_analysis: List[ClauseAnalysis]
    risk_summary: str