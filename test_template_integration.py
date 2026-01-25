#!/usr/bin/env python3
"""
Test script for professional LaTeX template integration.
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from renderers.docx_renderer import DocxRenderer

def test_escape_latex():
    """Test LaTeX character escaping."""
    test_cases = [
        ("Hello & goodbye", r"Hello \& goodbye"),
        ("100% complete", r"100\% complete"),
        ("Cost: $50", r"Cost: \$50"),
        ("Use #hashtag", r"Use \#hashtag"),
        ("snake_case", r"snake\_case"),
        ("a{b}", r"a\{b\}"),
        ("~tilde", r"\textasciitilde{}tilde"),
        ("x^2", r"x\textasciicircum{}2"),
    ]
    
    renderer = DocxRenderer()
    
    print("Testing LaTeX character escaping:")
    for input_text, expected in test_cases:
        result = renderer._escape_latex(input_text)
        status = "✓" if result == expected else "✗"
        print(f"  {status} {input_text!r} → {result!r}")
        if result != expected:
            print(f"      Expected: {expected!r}")
    
    print("\n✅ All escape tests completed!")

def test_renderer_creation():
    """Test that DocxRenderer can be instantiated."""
    try:
        renderer = DocxRenderer()
        print(f"✅ DocxRenderer created successfully")
        print(f"   Template dir: {renderer.templates_dir}")
        print(f"   Outputs dir: {renderer.outputs_dir}")
        print(f"   Template path: {renderer.template_path}")
        print(f"   Template exists: {renderer.template_path.exists()}")
    except Exception as e:
        print(f"✗ Failed to create DocxRenderer: {e}")

if __name__ == "__main__":
    print("=" * 60)
    print("Testing Professional LaTeX Template Integration")
    print("=" * 60)
    print()
    
    test_renderer_creation()
    print()
    test_escape_latex()
    print()
    print("=" * 60)
    print("Tests completed!")
    print("=" * 60)
