"""
Request and response models for API endpoints.
"""
from typing import Optional
from pydantic import BaseModel, Field


class TailorRequest(BaseModel):
    """Request model for tailoring CV and cover letter."""
    job_description: str = Field(..., min_length=50, description="Job description text")
    company_name: Optional[str] = Field(None, description="Company name (optional)")
    role_title: Optional[str] = Field(None, description="Role title (optional)")


class TokenUsage(BaseModel):
    """Token usage and cost tracking."""
    cv_input_tokens: int = 0
    cv_output_tokens: int = 0
    cl_input_tokens: int = 0
    cl_output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    estimated_cost_eur: float = 0.0
    currency: str = "USD"  # Google charges in USD, converted to EUR


class TailorResponse(BaseModel):
    """Response model for tailoring endpoint."""
    job_id: str
    status: str = "success"
    cv_path: str
    cover_letter_path: str
    token_usage: TokenUsage
    message: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str
    detail: str
    status_code: int = 500
