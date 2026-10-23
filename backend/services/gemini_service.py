"""
Google Gemini API service for CV and cover letter tailoring.
Handles API calls, token tracking, cost estimation, and error handling.
"""
import os
import time
from typing import Optional, Tuple

from google import genai
from google.genai import types
from dotenv import load_dotenv

from models.requests import TokenUsage

# Load environment variables
load_dotenv()

# Gemini API Configuration
DEFAULT_MODEL = "gemini-3.8-flash"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.3"))
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "8000"))

# Pricing (per 1M tokens in USD), verified against ai.google.dev on 2026-10-23.
# Free tier: 15 requests/min, 1.5M tokens/day
PRICING = {
    # Introductory pricing through December 31, 2026; then $1.50 / $7.50.
    "gemini-3.8-flash": {
        "input": 0.75,
        "output": 3.75,
    },
    # --- GEMINI 3 SERIES ---
    # gemini-3-pro-preview was shut down and has been removed rather than mispriced.
    "gemini-3-flash-preview": {
        "input": 0.50,       # $0.50 / 1M
        "output": 3.00,      # $3.00 / 1M
    },

    # --- GEMINI 2.5 SERIES: Stable production models ---
    "gemini-2.5-pro": {
        "input": 1.25,       # $1.25 / 1M (<= 200k context)
        "input_long": 2.50,  # $2.50 / 1M (> 200k context)
        "output": 10.00,     # $10.00 / 1M
        "output_long": 15.00 # $15.00 / 1M
    },
    "gemini-2.5-flash": {
        "input": 0.30,       # $0.30 / 1M
        "output": 2.50,      # $2.50 / 1M
    },
    "gemini-2.5-flash-lite": {
        "input": 0.10,       # $0.10 / 1M
        "output": 0.40,      # $0.40 / 1M
    },
}


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
    ) -> float:
        """
        Estimate cost for token usage in USD.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in USD
        """
        # An unlisted model must still be priced without crashing. Fall back to the
        # configured default's rates rather than to a removed legacy model.
        pricing = PRICING.get(self.model, PRICING[DEFAULT_MODEL])

        # Calculate cost per million tokens
        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]
        total_usd = input_cost + output_cost

        return total_usd

    def _call_gemini(
        self,
        prompt: str,
        max_retries: int = 3,
        max_output_tokens: Optional[int] = None
    ) -> Tuple[str, int, int]:
        """
        Call Gemini API with retry logic.

        Args:
            prompt: The prompt to send
            max_retries: Maximum number of retry attempts
            max_output_tokens: Override max_output_tokens for this call (uses self.max_output_tokens if None)

        Returns:
            Tuple of (response_text, input_tokens, output_tokens)

        Raises:
            GeminiServiceError: If API call fails after retries
        """
        # Use provided max_output_tokens or fall back to instance default
        tokens_limit = max_output_tokens if max_output_tokens is not None else self.max_output_tokens

        for attempt in range(max_retries):
            try:
                config = types.GenerateContentConfig(
                    temperature=self.temperature,
                    max_output_tokens=tokens_limit,
                )
                # Keep reasoning from exhausting the document response budget.
                if self.model == "gemini-3.8-flash":
                    config.thinking_config = types.ThinkingConfig(thinking_level="low")

                # Do not set response_mime_type="application/json": it causes premature
                # truncation of long document responses. Parsing is handled by
                # tailor_service._parse_json_response, which tolerates wrappers.
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config
                )

                # Check finish reason for debugging truncation issues
                if response.candidates and len(response.candidates) > 0:
                    finish_reason = response.candidates[0].finish_reason
                    # Log if it's not a natural stop (STOP = 1)
                    if finish_reason and finish_reason != 1:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"Gemini finish_reason: {finish_reason} (expected STOP=1)")

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

    def calculate_token_usage(
        self,
        cv_input_tokens: int,
        cv_output_tokens: int,
        cl_input_tokens: int,
        cl_output_tokens: int,
        cv_attempts: int = 1,
        cl_attempts: int = 1
    ) -> TokenUsage:
        """
        Calculate total token usage and costs.

        Args:
            cv_input_tokens: Total input tokens for CV tailoring (all attempts)
            cv_output_tokens: Total output tokens for CV tailoring (all attempts)
            cl_input_tokens: Total input tokens for cover letter (all attempts)
            cl_output_tokens: Total output tokens for cover letter (all attempts)
            cv_attempts: Number of attempts made for CV generation
            cl_attempts: Number of attempts made for cover letter generation

        Returns:
            TokenUsage object with costs in USD
        """
        total_input = cv_input_tokens + cl_input_tokens
        total_output = cv_output_tokens + cl_output_tokens
        total_tokens = total_input + total_output

        cost_usd = self._estimate_cost(total_input, total_output)

        return TokenUsage(
            cv_input_tokens=cv_input_tokens,
            cv_output_tokens=cv_output_tokens,
            cl_input_tokens=cl_input_tokens,
            cl_output_tokens=cl_output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=round(cost_usd, 6),
            cv_attempts=cv_attempts,
            cl_attempts=cl_attempts,
            model_name=self.model
        )
