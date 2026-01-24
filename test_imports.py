#!/usr/bin/env python3
"""Quick test to verify modules load correctly"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

try:
    print("Testing imports...")
    from services.tailor_service import tailor_documents, _slugify
    from renderers.docx_renderer import DocxRenderer
    print("✅ All imports successful")
    
    # Test slugify
    test_cases = [
        ("MediTech Solutions", "meditech_solutions"),
        ("Senior Analytics Manager", "senior_analytics_manager"),
        ("Data & Analytics", "data_analytics"),
    ]
    
    print("\nTesting _slugify function:")
    for input_val, expected in test_cases:
        result = _slugify(input_val)
        status = "✅" if result == expected else "❌"
        print(f"  {status} _slugify('{input_val}') = '{result}' (expected '{expected}')")
    
except Exception as e:
    print(f"❌ Import error: {e}")
    import traceback
    traceback.print_exc()
