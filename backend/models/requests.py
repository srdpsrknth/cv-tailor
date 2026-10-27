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
    use_cache: bool = Field(
        True,
        description=(
            "Reuse a stored validated generation for the identical profile, posting, "
            "prompts, schema and model (Phase 3 item 5). Set false to force a fresh "
            "draft; the fresh result is still stored."
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
    #: Which route the run was billed on. Part of the record because the same model
    #: costs different amounts direct and through a gateway, so a model name alone
    #: does not identify a price (D-3/D-4).
    provider: Optional[str] = None


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
    #: Which provider and models actually produced this document set.
    #:
    #: Recorded because a generated CV is otherwise **unattributable**: the job folder
    #: is named after the case and a timestamp, so nothing on disk said which model
    #: wrote it. That is harmless for a single application and a real problem for a
    #: study comparing eight of them -- the first reading packet could not be used for
    #: the judgement it was built for, because the reader had no way to tell which model
    #: produced which document. The cache entry carried this information and the
    #: manifest did not, which is the kind of asymmetry only a comparison exposes.
    provider: Optional[str] = None
    models: Optional[Dict[str, str]] = None
