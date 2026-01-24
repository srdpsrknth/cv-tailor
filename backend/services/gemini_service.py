"""
Google Gemini API service for CV and cover letter tailoring.
Handles API calls, token tracking, cost estimation, and error handling.
"""
import os
import json
import time
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

from google import genai
from google.genai import types
from dotenv import load_dotenv

from models.profile import Profile
from models.tailored_output import TailoredCV, TailoredCoverLetter
from models.requests import TokenUsage

# Load environment variables
load_dotenv()

# Gemini API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.3"))
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "8000"))

# Pricing (as of Jan 2026, Gemini 2.5 Flash)
# Free tier: 15 requests/min, 1.5M tokens/day
# Paid tier pricing (per 1M tokens)
PRICING = {
    "gemini-2.5-flash": {
        "input": 0.00015,  # $0.00015 per 1K input tokens
        "output": 0.0006,  # $0.0006 per 1K output tokens
    },
    "gemini-2.0-flash": {
        "input": 0.00015,
        "output": 0.0006,
    },
    "gemini-1.5-flash": {
        "input": 0.00015,
        "output": 0.0006,
    },
    "gemini-1.5-pro": {
        "input": 0.00125,
        "output": 0.005,
    }
}

# USD to EUR conversion rate (approximate - update as needed)
USD_TO_EUR = 0.92


class GeminiServiceError(Exception):
    """Custom exception for Gemini service errors."""
    pass


class GeminiService:
    """Service for interacting with Google Gemini API."""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Gemini service.
        
        Args:
            api_key: Google Gemini API key (defaults to env var)
        """
        self.api_key = api_key or GEMINI_API_KEY
        if not self.api_key:
            raise GeminiServiceError(
                "GEMINI_API_KEY not found. Set it in .env file or pass to constructor."
            )
        
        self.client = genai.Client(api_key=self.api_key)
        self.model = GEMINI_MODEL
        self.temperature = GEMINI_TEMPERATURE
        self.max_output_tokens = GEMINI_MAX_OUTPUT_TOKENS
    
    def _estimate_cost(
        self, 
        input_tokens: int, 
        output_tokens: int
    ) -> Tuple[float, float]:
        """
        Estimate cost for token usage.
        
        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            2
        Returns:
            Tuple of (cost_usd, cost_eur)
        """
        pricing = PRICING.get(self.model, PRICING["gemini-1.5-flash"])
        
        # Calculate cost per 1000 tokens
        input_cost = (input_tokens / 1000) * pricing["input"]
        output_cost = (output_tokens / 1000) * pricing["output"]
        total_usd = input_cost + output_cost
        total_eur = total_usd * USD_TO_EUR
        
        return total_usd, total_eur
    
    def _call_gemini(
        self, 
        prompt: str, 
        response_schema: Optional[Dict[str, Any]] = None,
        max_retries: int = 3
    ) -> Tuple[str, int, int]:
        """
        Call Gemini API with retry logic.
        
        Args:
            prompt: The prompt to send
            response_schema: Optional JSON schema for structured output
            max_retries: Maximum number of retry attempts
            
        Returns:
            Tuple of (response_text, input_tokens, output_tokens)
            
        Raises:
            GeminiServiceError: If API call fails after retries
        """
        for attempt in range(max_retries):
            try:
                config = types.GenerateContentConfig(
                    temperature=self.temperature,
                    max_output_tokens=self.max_output_tokens,
                )
                
                # Add JSON mode if schema provided
                if response_schema:
                    config.response_mime_type = "application/json"
                    config.response_schema = response_schema
                else:
                    # Request JSON output without strict schema
                    config.response_mime_type = "application/json"
                
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config
                )
                
                # Extract token usage
                usage = response.usage_metadata
                input_tokens = usage.prompt_token_count if usage else 0
                output_tokens = usage.candidates_token_count if usage else 0
                
                return response.text, input_tokens, output_tokens
                
            except Exception as e:
                if attempt < max_retries - 1:
                    # Exponential backoff
                    wait_time = 2 ** attempt
                    print(f"Gemini API error (attempt {attempt + 1}/{max_retries}): {e}")
                    print(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    raise GeminiServiceError(f"Gemini API call failed after {max_retries} attempts: {e}")
    
    def tailor_cv(
        self, 
        profile: Profile, 
        job_description: str,
        prompt_template: str
    ) -> Tuple[TailoredCV, int, int]:
        """
        Tailor CV based on job description.
        
        Args:
            profile: Base profile
            job_description: Job description text
            prompt_template: Prompt template with placeholders
            
        Returns:
            Tuple of (TailoredCV, input_tokens, output_tokens)
        """
        # Build prompt
        prompt = prompt_template.format(
            profile=profile.model_dump_json(indent=2),
            job_description=job_description
        )
        
        # Define response schema for structured output
        response_schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "array", "items": {"type": "string"}},
                "skills": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "experience": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "company": {"type": "string"},
                            "role": {"type": "string"},
                            "start_date": {"type": "string"},
                            "end_date": {"type": "string"},
                            "bullets": {"type": "array", "items": {"type": "string"}},
                            "selected_project_names": {"type": "array", "items": {"type": "string"}},
                            "project_bullets": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["company", "role", "start_date", "end_date", "bullets"]
                    }
                }
            },
            "required": ["summary", "skills", "experience"]
        }
        
        # Call API
        response_text, input_tokens, output_tokens = self._call_gemini(
            prompt, 
            response_schema=response_schema
        )
        
        # Parse response
        try:
            data = json.loads(response_text)
            tailored_cv = TailoredCV(**data)
            return tailored_cv, input_tokens, output_tokens
        except (json.JSONDecodeError, ValueError) as e:
            raise GeminiServiceError(f"Failed to parse CV response: {e}\nResponse: {response_text}")
    
    def generate_cover_letter(
        self,
        profile: Profile,
        job_description: str,
        company_name: str,
        role_title: str,
        prompt_template: str
    ) -> Tuple[TailoredCoverLetter, int, int]:
        """
        Generate cover letter based on job description.
        
        Args:
            profile: Base profile
            job_description: Job description text
            company_name: Company name
            role_title: Role title
            prompt_template: Prompt template with placeholders
            
        Returns:
            Tuple of (TailoredCoverLetter, input_tokens, output_tokens)
        """
        # Build prompt
        prompt = prompt_template.format(
            profile=profile.model_dump_json(indent=2),
            job_description=job_description,
            company_name=company_name,
            role_title=role_title
        )
        
        # Define response schema
        response_schema = {
            "type": "object",
            "properties": {
                "role_title": {"type": "string"},
                "company_name": {"type": "string"},
                "paragraphs": {"type": "array", "items": {"type": "string"}},
                "highlight_bullets": {"type": "array", "items": {"type": "string"}},
                "closing_line": {"type": "string"},
                "signature_name": {"type": "string"}
            },
            "required": ["role_title", "company_name", "paragraphs", "signature_name"]
        }
        
        # Call API
        response_text, input_tokens, output_tokens = self._call_gemini(
            prompt,
            response_schema=response_schema
        )
        
        # Parse response
        try:
            data = json.loads(response_text)
            cover_letter = TailoredCoverLetter(**data)
            return cover_letter, input_tokens, output_tokens
        except (json.JSONDecodeError, ValueError) as e:
            raise GeminiServiceError(f"Failed to parse cover letter response: {e}\nResponse: {response_text}")
    
    def calculate_token_usage(
        self,
        cv_input_tokens: int,
        cv_output_tokens: int,
        cl_input_tokens: int,
        cl_output_tokens: int
    ) -> TokenUsage:
        """
        Calculate total token usage and costs.
        
        Args:
            cv_input_tokens: Input tokens for CV tailoring
            cv_output_tokens: Output tokens for CV tailoring
            cl_input_tokens: Input tokens for cover letter
            cl_output_tokens: Output tokens for cover letter
            
        Returns:
            TokenUsage object with costs in USD and EUR
        """
        total_input = cv_input_tokens + cl_input_tokens
        total_output = cv_output_tokens + cl_output_tokens
        total_tokens = total_input + total_output
        
        cost_usd, cost_eur = self._estimate_cost(total_input, total_output)
        
        return TokenUsage(
            cv_input_tokens=cv_input_tokens,
            cv_output_tokens=cv_output_tokens,
            cl_input_tokens=cl_input_tokens,
            cl_output_tokens=cl_output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=round(cost_usd, 4),
            estimated_cost_eur=round(cost_eur, 4),
            currency="USD"
        )
    
    def validate_api_key(self) -> bool:
        """
        Validate that the API key works.
        
        Returns:
            True if valid, raises exception otherwise
        """
        try:
            # Simple test call
            self.client.models.generate_content(
                model=self.model,
                contents="Hello",
                config=types.GenerateContentConfig(max_output_tokens=10)
            )
            return True
        except Exception as e:
            raise GeminiServiceError(f"API key validation failed: {e}")


# Convenience function for external use
def create_gemini_service(api_key: Optional[str] = None) -> GeminiService:
    """
    Create and return a GeminiService instance.
    
    Args:
        api_key: Optional API key (defaults to env var)
        
    Returns:
        Initialized GeminiService
    """
    return GeminiService(api_key=api_key)
