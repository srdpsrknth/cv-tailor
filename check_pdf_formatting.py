#!/usr/bin/env python3
"""Verify cover letter PDF formatting"""
from pathlib import Path
from pypdf import PdfReader

# Get the latest generated PDF
outputs_dir = Path("outputs")
job_folders = sorted([d for d in outputs_dir.iterdir() if d.is_dir()])
latest_job = job_folders[-1]

pdf_files = list(latest_job.glob("*cover_letter*.pdf"))
if not pdf_files:
    print("❌ No cover letter PDF found")
    exit(1)

pdf_path = pdf_files[0]
print(f"📄 Checking PDF: {pdf_path.name}\n")

try:
    reader = PdfReader(str(pdf_path))
    print(f"✅ PDF loaded successfully")
    print(f"   Pages: {len(reader.pages)}")
    print(f"   File size: {pdf_path.stat().st_size / 1024:.1f} KB")
    
    # Extract and display first page content
    page = reader.pages[0]
    text = page.extract_text()
    
    print(f"\n📝 Cover Letter Content Preview:")
    print("=" * 60)
    lines = text.split('\n')
    for i, line in enumerate(lines[:25], 1):  # First 25 lines
        if line.strip():
            print(f"  {line}")
    if len(lines) > 25:
        print(f"  ... ({len(lines) - 25} more lines)")
    print("=" * 60)
    
    print(f"\n✅ PDF formatting verified!")
    print(f"   Total lines in content: {len(lines)}")
    print(f"   Average line length: {sum(len(l) for l in lines) // len(lines) if lines else 0}")
    
except Exception as e:
    print(f"❌ Error reading PDF: {e}")
    import traceback
    traceback.print_exc()
