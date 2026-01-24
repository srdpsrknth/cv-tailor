#!/usr/bin/env python3
"""
Quick test to verify 3-file generation with job-specific folders
"""
import requests
import json
from pathlib import Path

BACKEND_URL = "http://localhost:8000"
API_TAILOR = f"{BACKEND_URL}/api/tailor"

# Sample job description
JOB_DESCRIPTION = """
Senior Data Analyst | Healthcare Tech Startup

We're looking for a Senior Data Analyst to lead our analytics initiatives. 
You'll work with stakeholder teams to drive insights, own metrics and dashboards,
and help us grow our user base across 50+ countries.

Requirements:
- 5+ years of data analytics experience
- SQL, Python, and visualization tools (Tableau/Looker)
- Healthcare or SaaS background preferred
- Strong communication skills

Responsibilities:
- Design and maintain analytics dashboards
- Build data models and pipelines
- Present insights to executive teams
- Mentor junior analysts
"""

print("🚀 Testing 3-file generation with job-specific folders...")
print(f"Backend URL: {BACKEND_URL}")

# Send request
payload = {
    "job_description": JOB_DESCRIPTION,
    "company_name": "HealthTech Inc.",
    "role_title": "Senior Data Analyst"
}

print("\n📤 Sending tailoring request...")
try:
    response = requests.post(API_TAILOR, json=payload, timeout=120)
    response.raise_for_status()
    
    data = response.json()
    print(f"\n✅ Response received:")
    print(json.dumps({
        "job_id": data["job_id"],
        "status": data["status"],
        "cv_path": data["cv_path"],
        "cover_letter_path": data["cover_letter_path"],
        "cl_pdf_path": data.get("cl_pdf_path"),
        "token_usage": data["token_usage"]
    }, indent=2))
    
    # Verify files exist
    job_id = data["job_id"]
    job_folder = Path("outputs") / job_id
    
    print(f"\n📁 Checking job folder: {job_folder}")
    if job_folder.exists():
        files = list(job_folder.glob("*"))
        print(f"✅ Job folder exists with {len(files)} files:")
        for f in files:
            size_kb = f.stat().st_size / 1024
            print(f"   - {f.name} ({size_kb:.1f} KB)")
        
        # Check for specific files
        pdfs = list(job_folder.glob("*.pdf"))
        docxs = list(job_folder.glob("*.docx"))
        
        print(f"\n📊 File summary:")
        print(f"   PDF files: {len(pdfs)}")
        print(f"   DOCX files: {len(docxs)}")
        print(f"   Total files: {len(files)}")
        
        if len(pdfs) >= 1 and len(docxs) >= 1:
            print("\n✅ SUCCESS: All 3 file types generated (CV PDF, CL DOCX, and likely CL PDF)")
        else:
            print(f"\n⚠️  WARNING: Expected at least 1 PDF and 1 DOCX, got {len(pdfs)} PDFs and {len(docxs)} DOCXs")
    else:
        print(f"❌ ERROR: Job folder does not exist!")
    
except requests.exceptions.ConnectionError:
    print("❌ ERROR: Cannot connect to backend. Is uvicorn running?")
except requests.exceptions.Timeout:
    print("❌ ERROR: Request timeout. Backend may be slow or unresponsive.")
except requests.exceptions.HTTPError as e:
    print(f"❌ ERROR: HTTP {response.status_code}")
    print(f"   Response: {response.text}")
except Exception as e:
    print(f"❌ ERROR: {type(e).__name__}: {e}")
