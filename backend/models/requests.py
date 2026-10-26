"""
Request and response models for API endpoints.
"""
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class TailorRequest(BaseModel):
    """Request model for tailoring CV and cover letter."""
    job_description: str = Field(..., min_length=50, description="Job description text")
    company_name: Optional[str] = Field(None, description="Company name (optional)")
    role_title: Optional[str] = Field(None, description="Role title (optional)")
    work_country: Optional[str] = Field(None, max_length=100, description="Actual country of employment, not company headquarters")
    profile_id: Optional[str] = Field(
        None,
        description=(
            "Which candidate to tailor for. Optional here only because it may come "
            "from CVTAILOR_PROFILE_ID instead; there is no default profile and the "
            "request fails closed when neither is set (ADR 0003)."
        ),
    )


class TokenUsage(BaseModel):
    """Token usage and cost tracking."""
    cv_input_tokens: int = 0
    cv_output_tokens: int = 0
    cl_input_tokens: int = 0
    cl_output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cv_attempts: int = 1
    cl_attempts: int = 1
    model_name: str = "gemini-2.5-flash"


class TailorResponse(BaseModel):
    """Response model for tailoring endpoint."""
    job_id: str
    status: str = "success"
    cv_path: str
    cover_letter_path: str
    cl_pdf_path: Optional[str] = None
    cv_page_count: Optional[int] = None
    cover_letter_page_count: Optional[int] = None
    source_path: Optional[str] = None
    token_usage: TokenUsage
    tailoring_explanation: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
