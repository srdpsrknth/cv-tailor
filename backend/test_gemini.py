"""
Test script for Gemini service.
Run this to validate API connectivity and test the service.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from services.gemini_service import create_gemini_service, GeminiServiceError
from services.profile_loader import load_profile


def test_gemini_service():
    """Test Gemini service connectivity and basic functionality."""
    print("=" * 60)
    print("Testing Gemini Service")
    print("=" * 60)
    
    try:
        # Create service
        print("\n1. Initializing Gemini service...")
        service = create_gemini_service()
        print(f"   Model: {service.model}")
        print(f"   Temperature: {service.temperature}")
        print(f"   Max tokens: {service.max_output_tokens}")
        
        # Validate API key
        print("\n2. Validating API key...")
        service.validate_api_key()
        print("   API key is valid!")
        
        # Load profile
        print("\n3. Loading base profile...")
        profile = load_profile()
        print(f"   Profile loaded: {profile.identity.full_name}")
        
        # Test simple call
        print("\n4. Testing simple API call...")
        prompt = "Say 'Hello from Gemini!' in exactly 5 words."
        response, input_tokens, output_tokens = service._call_gemini(prompt)
        print(f"   Response: {response}")
        print(f"   Tokens: {input_tokens} in, {output_tokens} out")
        
        # Calculate cost estimate
        print("\n5. Testing cost calculation...")
        token_usage = service.calculate_token_usage(
            cv_input_tokens=1500,
            cv_output_tokens=2000,
            cl_input_tokens=1200,
            cl_output_tokens=800
        )
        print(f"   Total tokens: {token_usage.total_tokens}")
        print(f"   Estimated cost: ${token_usage.estimated_cost_usd:.4f} USD")
        print(f"   Estimated cost: €{token_usage.estimated_cost_eur:.4f} EUR")
        
        print("\n" + "=" * 60)
        print("SUCCESS: All tests passed!")
        print("=" * 60)
        return True
        
    except GeminiServiceError as e:
        print(f"\nERROR: Gemini service error - {e}")
        return False
    except Exception as e:
        print(f"\nERROR: Unexpected error - {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_gemini_service()
    sys.exit(0 if success else 1)
