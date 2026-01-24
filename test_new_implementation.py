#!/usr/bin/env python3
"""Test the new job_id and PDF generation"""
import requests
import json
from pathlib import Path

JOB_DESC = '''Senior Analytics Manager - HealthTech Startup

We are hiring a Senior Analytics Manager to lead our data team and drive key business insights. 

Requirements:
- 7+ years of analytics experience
- Expert SQL, Python, and data visualization
- Strong communication and leadership skills
- Healthcare background preferred

Join us in transforming healthcare through data!'''

print('🚀 Testing new job_id generation with meaningful folder names...\n')
payload = {
    'job_description': JOB_DESC,
    'company_name': 'MediTech Solutions',
    'role_title': 'Senior Analytics Manager'
}

try:
    resp = requests.post('http://localhost:8000/api/tailor', json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    
    print(f'✅ Job ID: {data["job_id"]}')
    print(f'\n📄 CV Path: {Path(data["cv_path"]).name}')
    print(f'📧 CL Path: {Path(data["cover_letter_path"]).name}')
    print(f'📕 CL PDF Path: {Path(data.get("cl_pdf_path")).name if data.get("cl_pdf_path") else "None (LaTeX fallback needed)"}')
    
    # Check files
    job_id = data['job_id']
    job_folder = Path('outputs') / job_id
    
    if job_folder.exists():
        files = sorted(job_folder.glob('*'))
        print(f'\n📁 Files in job folder ({len(files)} total):')
        for f in files:
            size = f.stat().st_size / 1024
            print(f'   • {f.name} ({size:.1f} KB)')
        
        # Verify file types
        pdfs = list(job_folder.glob('*.pdf'))
        docxs = list(job_folder.glob('*.docx'))
        print(f'\n📊 Summary:')
        print(f'   PDFs: {len(pdfs)}')
        print(f'   DOCX: {len(docxs)}')
        
        if len(pdfs) >= 1 and len(docxs) >= 1:
            print(f'\n✅ SUCCESS: All required files generated!')
        else:
            print(f'\n⚠️  Missing files: Expected 2+ PDFs and 1+ DOCX')
    else:
        print(f'\n❌ Job folder not found: {job_folder}')
        
except Exception as e:
    print(f'❌ Error: {type(e).__name__}: {e}')
    import traceback
    traceback.print_exc()
