#!/usr/bin/env python3
"""
Integration test for professional LaTeX template PDF generation.
"""
import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

# Set minimal environment variables if needed
os.environ.setdefault("GEMINI_API_KEY", "test_key")

from renderers.docx_renderer import DocxRenderer
from models.tailored_output import TailoredCoverLetter
from models.profile import Profile

def test_pdf_generation_with_template():
    """Test PDF generation using the professional LaTeX template."""
    print("\n" + "=" * 70)
    print("TEST: PDF Generation with Professional LaTeX Template")
    print("=" * 70)
    
    # Create a test cover letter
    test_cl = TailoredCoverLetter(
        role_title="Senior Analytics Manager",
        company_name="MediTech Solutions",
        paragraphs=[
            "I am writing to express my strong interest in the Senior Analytics Manager position at MediTech Solutions. With over 8 years of experience in data analysis and strategic insights, I am confident in my ability to drive data-driven decision-making for your organization.",
            "Throughout my career, I have demonstrated expertise in translating complex datasets into actionable business insights. At my previous role, I led the implementation of a comprehensive analytics framework that identified $2M in revenue optimization opportunities.",
            "My technical proficiency spans SQL, Python, Tableau, and Google Analytics, complemented by strong business acumen and stakeholder management skills. I have successfully mentored cross-functional teams and built data cultures that prioritize evidence-based decision-making.",
            "I am particularly drawn to MediTech Solutions' mission to innovate healthcare solutions. I believe my experience in healthcare analytics and proven track record of driving measurable business impact position me as an excellent fit for this role."
        ],
        highlight_bullets=[
            "Led implementation of comprehensive analytics framework identifying $2M in revenue optimization",
            "8+ years of experience in data analysis and strategic insights",
            "Expertise in SQL, Python, Tableau, and Google Analytics",
        ],
        closing_line="Best regards,",
        signature_name="John Doe"
    )
    
    # Create test profile
    test_profile = Profile(
        version="1.0",
        identity={
            "full_name": "John Doe",
            "tagline": "Senior Data Analyst",
            "email": "john.doe@example.com",
            "phone": "+1-555-123-4567",
            "linkedin": "https://linkedin.com/in/johndoe",
            "github": "https://github.com/johndoe",
            "location": "San Francisco, CA",
        }
    )
    
    # Initialize renderer
    try:
        renderer = DocxRenderer()
        print(f"✓ Renderer initialized")
        print(f"  Outputs directory: {renderer.outputs_dir}")
    except Exception as e:
        print(f"✗ Failed to initialize renderer: {e}")
        return False
    
    # Render using the public API
    try:
        docx_path, pdf_path = renderer.render_cover_letter(test_cl, test_profile)
        
        print(f"\n✓ Cover letter rendered successfully!")
        print(f"  DOCX path: {docx_path}")
        print(f"  DOCX exists: {Path(docx_path).exists()}")
        print(f"  DOCX size: {Path(docx_path).stat().st_size if Path(docx_path).exists() else 'N/A'} bytes")
        
        if pdf_path:
            print(f"\n✓ PDF generated using professional LaTeX template!")
            print(f"  PDF path: {pdf_path}")
            print(f"  PDF exists: {Path(pdf_path).exists()}")
            
            if Path(pdf_path).exists():
                pdf_size = Path(pdf_path).stat().st_size
                print(f"  PDF size: {pdf_size} bytes")
                
                # Verify it's a valid PDF
                with open(pdf_path, 'rb') as f:
                    header = f.read(4)
                    if header == b'%PDF':
                        print(f"  ✓ PDF header verified (valid PDF file)")
                    else:
                        print(f"  ✗ Invalid PDF header")
                        return False
            else:
                print(f"✗ PDF file not created at {pdf_path}")
                return False
        else:
            print(f"✗ PDF generation failed (returned None)")
            return False
            
    except Exception as e:
        print(f"✗ Cover letter rendering failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print(f"\n" + "=" * 70)
    print("✅ Professional LaTeX Template Integration Test PASSED")
    print("=" * 70)
    return True

def check_template_files():
    """Verify that template files exist."""
    print("\n" + "=" * 70)
    print("CHECK: Professional LaTeX Template Files")
    print("=" * 70)
    
    template_root = Path(__file__).parent / "cover_letter_latex_template"
    
    files_to_check = [
        template_root / "main.tex",
        template_root / "setup" / "preamble.tex",
        template_root / "setup" / "macros.tex",
    ]
    
    all_exist = True
    for file_path in files_to_check:
        exists = file_path.exists()
        status = "✓" if exists else "✗"
        print(f"{status} {file_path.relative_to(Path(__file__).parent)}")
        if not exists:
            all_exist = False
    
    print()
    return all_exist

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("PROFESSIONAL LATEX TEMPLATE INTEGRATION TEST SUITE")
    print("=" * 70)
    
    # Check template files
    if not check_template_files():
        print("\n⚠ Some template files are missing!")
        print("The professional template will not work without all files.")
        sys.exit(1)
    
    # Run integration test
    success = test_pdf_generation_with_template()
    
    sys.exit(0 if success else 1)
