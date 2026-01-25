#!/usr/bin/env python3
"""
End-to-end test: Professional template integration with full render_cover_letter() API
"""
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from renderers.docx_renderer import DocxRenderer
from models.tailored_output import TailoredCoverLetter
from models.profile import Profile

def main():
    print("\n" + "="*80)
    print("END-TO-END TEST: Professional LaTeX Template Integration")
    print("="*80)
    
    # Create sample data
    cover_letter = TailoredCoverLetter(
        role_title="Data Scientist",
        company_name="Google",
        paragraphs=[
            "I am excited to apply for the Data Scientist position at Google. With extensive experience in machine learning and data analysis, I am confident I can contribute meaningfully to your team.",
            "In my current role, I have developed and deployed machine learning models that improved prediction accuracy by 35% and reduced inference time by 50%. I have also mentored junior engineers on best practices in model development.",
            "I am particularly drawn to Google's commitment to innovation and ethical AI. I believe my technical skills, combined with my passion for solving complex problems, make me an excellent fit for this role.",
        ],
        highlight_bullets=[
            "Developed ML models improving prediction accuracy by 35%",
            "Mentored 5+ junior engineers on ML best practices",
            "Published research on model optimization techniques"
        ],
        closing_line="Thank you for your consideration.",
        signature_name="Alice Smith"
    )
    
    profile = Profile(
        version="1.0",
        identity={
            "full_name": "Alice Smith",
            "tagline": "Data Scientist",
            "email": "alice.smith@example.com",
            "phone": "+1-650-555-0100",
            "linkedin": "https://linkedin.com/in/alicesmith",
            "github": "https://github.com/alicesmith",
            "location": "Mountain View, CA",
        }
    )
    
    # Test renderer
    try:
        renderer = DocxRenderer()
        print(f"\n✓ DocxRenderer initialized")
        print(f"  Template path: {renderer.template_path}")
        print(f"  Template exists: {renderer.template_path.exists()}")
        print(f"  Outputs dir: {renderer.outputs_dir}")
    except Exception as e:
        print(f"✗ Failed to initialize: {e}")
        return False
    
    # Render cover letter (public API)
    try:
        docx_path, pdf_path = renderer.render_cover_letter(cover_letter, profile)
        
        print(f"\n✓ render_cover_letter() completed successfully!")
        print(f"\n  DOCX Output:")
        print(f"    Path: {docx_path}")
        docx_exists = Path(docx_path).exists()
        print(f"    Exists: {docx_exists}")
        if docx_exists:
            print(f"    Size: {Path(docx_path).stat().st_size:,} bytes")
        
        print(f"\n  PDF Output:")
        print(f"    Path: {pdf_path}")
        pdf_exists = Path(pdf_path).exists() if pdf_path else False
        print(f"    Exists: {pdf_exists}")
        if pdf_exists:
            size = Path(pdf_path).stat().st_size
            print(f"    Size: {size:,} bytes")
            
            # Validate PDF
            with open(pdf_path, 'rb') as f:
                header = f.read(4)
                is_valid = header == b'%PDF'
                print(f"    Valid PDF: {is_valid}")
                if not is_valid:
                    print(f"    ✗ Invalid PDF header: {header}")
                    return False
        
        if not docx_exists or not pdf_exists:
            print(f"\n✗ Not all files were created!")
            return False
        
    except Exception as e:
        print(f"✗ render_cover_letter() failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print(f"\n" + "="*80)
    print("✅ END-TO-END TEST PASSED - Professional Template Fully Integrated!")
    print("="*80)
    print(f"\nGenerated Files:")
    print(f"  1. DOCX: {Path(docx_path).name}")
    print(f"  2. PDF:  {Path(pdf_path).name}")
    print(f"\nThe professional LaTeX template is now being used for all PDF generation!")
    print()
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
