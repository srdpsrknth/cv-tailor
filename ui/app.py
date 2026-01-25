"""
CV & Cover Letter Tailor - Streamlit UI
Provides an interactive interface for tailoring CVs and cover letters to job descriptions.
"""

import streamlit as st
import requests
import streamlit.components.v1 as components
from pathlib import Path
import base64
from io import BytesIO

# Configuration
BACKEND_URL = "http://localhost:8000"
API_TAILOR = f"{BACKEND_URL}/api/tailor"
API_DOWNLOAD_CV = f"{BACKEND_URL}/api/download/cv"
API_DOWNLOAD_CL = f"{BACKEND_URL}/api/download/cover-letter"
API_DOWNLOAD_CL_PDF = f"{BACKEND_URL}/api/download/cover-letter-pdf"
API_PREVIEW_CV = f"{BACKEND_URL}/api/preview"

# Page config
st.set_page_config(
    page_title="CV & Cover Letter Tailor",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Title and description
st.title("📄 CV & Cover Letter Tailor")
st.markdown(
    """
    Tailor your CV and generate a compelling cover letter for any job application.
    Powered by AI-driven insights from your profile and the job description.
    """
)

# Sidebar for info
with st.sidebar:
    st.header("ℹ️ About")
    st.markdown(
        """
        **How it works:**
        1. Paste the job description
        2. (Optional) Enter company name and role title
        3. Click "Generate"
        4. Review, download, and apply!
        
        **Tech Stack:**
        - Backend: FastAPI + Google Gemini
        - CV: LaTeX → PDF (pdflatex)
        - Cover Letter: DOCX (Aptos font)
        
        **Free tier:** 15 requests/min, 1.5M tokens/day
        """
    )

# ============================================================================
# Main UI
# ============================================================================

# Input section
st.header("📝 Job Description")
job_description = st.text_area(
    "Paste the full job description here",
    height=250,
    placeholder="e.g., About the job...\n\nWe are looking for a Data Analyst...",
    key="job_desc"
)

col1, col2 = st.columns(2)
with col1:
    company_name = st.text_input(
        "Company Name (optional)",
        placeholder="e.g., trivago",
        key="company"
    )

with col2:
    role_title = st.text_input(
        "Role Title (optional)",
        placeholder="e.g., Senior Data Analyst",
        key="role"
    )

# Generate button
col_btn_left, col_btn_center, col_btn_right = st.columns([1, 2, 1])
with col_btn_center:
    generate_btn = st.button(
        "🚀 Generate CV & Cover Letter",
        use_container_width=True,
        disabled=not job_description.strip() or len(job_description.strip()) < 50,
        type="primary"
    )

# ============================================================================
# Generation logic
# ============================================================================

if generate_btn:
    if not job_description.strip():
        st.error("❌ Please provide a job description (at least 50 characters).")
    else:
        # Show spinner while generating
        with st.spinner("🔄 Generating tailored documents... (this may take 30-60 seconds)"):
            try:
                # Call backend API
                payload = {
                    "job_description": job_description,
                    "company_name": company_name.strip() if company_name else None,
                    "role_title": role_title.strip() if role_title else None,
                }

                response = requests.post(
                    API_TAILOR,
                    json=payload,
                    timeout=120
                )

                if response.status_code == 200:
                    data = response.json()
                    
                    # Debug: Check what's in the response
                    st.write("DEBUG - Response keys:", list(data.keys()))
                    if "tailoring_explanation" in data:
                        st.write("DEBUG - Explanation present:", bool(data["tailoring_explanation"]))
                    
                    # Store in session state for later use
                    st.session_state.job_id = data["job_id"]
                    st.session_state.cv_path = data["cv_path"]
                    st.session_state.cover_letter_path = data["cover_letter_path"]
                    st.session_state.cl_pdf_path = data.get("cl_pdf_path")  # May be None
                    st.session_state.token_usage = data["token_usage"]
                    st.session_state.tailoring_explanation = data.get("tailoring_explanation")
                    st.session_state.generated = True

                    st.success("✅ Documents generated successfully!")
                    st.rerun()

                else:
                    error_msg = response.json().get("detail", "Unknown error")
                    st.error(f"❌ Backend error: {error_msg}")

            except requests.exceptions.Timeout:
                st.error("⏱️ Request timed out. Try again or check backend logs.")
            except requests.exceptions.ConnectionError:
                st.error("🔌 Cannot connect to backend. Ensure uvicorn is running on http://localhost:8000")
            except Exception as e:
                st.error(f"❌ Unexpected error: {str(e)}")

# ============================================================================
# Preview and download section
# ============================================================================

if "generated" in st.session_state and st.session_state.generated:
    st.divider()
    st.header("📑 Results")

    job_id = st.session_state.job_id
    token_usage = st.session_state.token_usage

    # Token usage and cost
    st.subheader("💰 Token Usage & Cost")
    col_t1, col_t2, col_t3, col_t4 = st.columns(4)
    with col_t1:
        st.metric("Input Tokens", f"{token_usage['cv_input_tokens']}")
    with col_t2:
        st.metric("Output Tokens", f"{token_usage['cv_output_tokens']}")
    with col_t3:
        st.metric("Total Tokens", f"{token_usage['total_tokens']}")
    with col_t4:
        st.metric("Est. Cost (EUR)", f"€{token_usage['estimated_cost_eur']:.4f}")

    st.divider()

    # Tailoring Explanation Section
    if "tailoring_explanation" in st.session_state and st.session_state.tailoring_explanation:
        with st.expander("📋 Tailoring Details & Changes Made", expanded=False):
            st.markdown("### How Your CV & Cover Letter Were Tailored")
            st.markdown(st.session_state.tailoring_explanation)
    
    st.divider()

    # Preview and download
    tab_cv, tab_cl = st.tabs(["📄 CV (PDF)", "📧 Cover Letter (DOCX)"])

    # CV Tab
    with tab_cv:
        st.subheader("📄 CV Preview & Download")
        
        try:
            # Fetch PDF for download/preview
            pdf_response = requests.get(
                f"{API_DOWNLOAD_CV}/{job_id}",
                timeout=30
            )
            if pdf_response.status_code == 200:
                # Offer download button prominently
                st.download_button(
                    label="📥 Download CV (PDF)",
                    data=pdf_response.content,
                    file_name=f"{job_id}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
                st.info(
                    "✅ PDF ready to download. Open in Adobe Reader or your browser to view. "
                    "(Note: PDF preview requires Adobe Reader or compatible viewer)"
                )
            else:
                st.error("Could not generate PDF. Please try again.")
        except Exception as e:
            st.error(f"Download error: {str(e)}")

    # Cover Letter Tab
    with tab_cl:
        st.subheader("📧 Cover Letter - DOCX & PDF")
        st.info(
            "✅ Your cover letter has been generated in both DOCX (Word) and PDF formats. "
            "Download whichever format you prefer and customize as needed."
        )

        col_cl_docx, col_cl_pdf = st.columns(2)
        
        with col_cl_docx:
            try:
                cl_response = requests.get(
                    f"{API_DOWNLOAD_CL}/{job_id}",
                    timeout=30
                )
                if cl_response.status_code == 200:
                    st.download_button(
                        label="📥 Download as DOCX (Word)",
                        data=cl_response.content,
                        file_name=f"{job_id}_cover_letter.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True
                    )
                else:
                    st.error("Could not download DOCX.")
            except Exception as e:
                st.error(f"Download error: {str(e)}")
        
        with col_cl_pdf:
            # Try the new dedicated PDF endpoint
            try:
                cl_pdf_response = requests.get(
                    f"{API_DOWNLOAD_CL_PDF}/{job_id}",
                    timeout=30
                )
                if cl_pdf_response.status_code == 200:
                    st.download_button(
                        label="📥 Download as PDF",
                        data=cl_pdf_response.content,
                        file_name=f"{job_id}_cover_letter.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
                else:
                    st.caption("(PDF not available - LibreOffice may not be installed)")
            except Exception:
                st.caption("(PDF not available - LibreOffice may not be installed)")
        

    st.divider()

    # New generation button
    if st.button("🔄 Generate Another", use_container_width=True):
        for key in ["generated", "job_id", "cv_path", "cover_letter_path", "token_usage"]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

else:
    # Empty state
    st.info(
        "👇 **Get started:** Paste a job description above and click 'Generate' to tailor your CV and cover letter!"
    )
