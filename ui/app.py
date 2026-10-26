"""
CV & Cover Letter Tailor - Streamlit UI
Provides an interactive interface for tailoring CVs and cover letters to job descriptions.
"""

import streamlit as st
import requests
import os
from pathlib import Path
from dotenv import load_dotenv

# Configuration
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
API_TAILOR = f"{BACKEND_URL}/api/tailor"
API_DOWNLOAD_CV = f"{BACKEND_URL}/api/download/cv"
API_DOWNLOAD_CL = f"{BACKEND_URL}/api/download/cover-letter"
API_DOWNLOAD_CL_PDF = f"{BACKEND_URL}/api/download/cover-letter-pdf"

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

work_country_choice = st.selectbox(
    "Country of employment",
    ["Germany", "Netherlands", "Ireland", "Denmark", "United Kingdom", "Switzerland", "Other"],
    key="work_country_choice",
    help="Choose where you will work, rather than the company's headquarters. For remote roles, use your country of employment.",
)
work_country = (
    st.text_input("Country name", key="work_country_other", placeholder="e.g., Sweden").strip()
    if work_country_choice == "Other" else work_country_choice
)
if work_country and work_country != "Germany":
    st.caption("The CV will show German EU Blue Card holder. The cover letter will mention employer support for local work authorization.")

# Generate button
col_btn_left, col_btn_center, col_btn_right = st.columns([1, 2, 1])
with col_btn_center:
    generate_btn = st.button(
        "🚀 Generate CV & Cover Letter",
        use_container_width=True,
        disabled=not job_description.strip() or len(job_description.strip()) < 50 or not work_country,
        type="primary"
    )

# ============================================================================
# Generation logic
# ============================================================================

if generate_btn:
    if not job_description.strip():
        st.error("❌ Please provide a job description (at least 50 characters).")
    else:
        # Show info about the process
        st.info(
            "ℹ️ **Generation Process:**\n\n"
            "1. AI drafts and reviews CV wording against your profile\n"
            "2. CV is rendered to PDF and checked for length (target: 2 pages)\n"
            "3. If CV exceeds 2 pages, content is automatically reduced and regenerated\n"
            "4. The app checks the cover letter structure and word count\n"
            "5. Results are shown only after the CV is within 2 pages\n\n"
            "*Review and layout checks may take several minutes.*"
        )

        # Progress placeholder
        progress_placeholder = st.empty()
        status_placeholder = st.empty()

        # Show spinner while generating
        with st.spinner("🔄 Step 1/4: Generating CV content with AI..."):
            try:
                # Call backend API
                payload = {
                    "job_description": job_description,
                    "company_name": company_name.strip() if company_name else None,
                    "role_title": role_title.strip() if role_title else None,
                    "work_country": work_country,
                }

                response = requests.post(
                    API_TAILOR,
                    json=payload,
                    timeout=600  # Includes factual review and bounded layout retries
                )

                if response.status_code == 200:
                    data = response.json()

                    # Store in session state for later use
                    st.session_state.job_id = data["job_id"]
                    st.session_state.token_usage = data["token_usage"]
                    st.session_state.tailoring_explanation = data.get("tailoring_explanation")
                    st.session_state.validation_message = data.get("message")
                    st.session_state.generated = True

                    progress_placeholder.empty()
                    status_placeholder.empty()
                    st.success("✅ Documents generated successfully!")
                    st.rerun()

                else:
                    error_msg = response.json().get("detail", "Unknown error")
                    progress_placeholder.empty()
                    status_placeholder.empty()
                    st.error(f"❌ Backend error: {error_msg}")

            except requests.exceptions.Timeout:
                progress_placeholder.empty()
                status_placeholder.empty()
                st.error("⏱️ Request timed out. The process may have needed multiple CV reduction iterations. Check backend logs.")
            except requests.exceptions.ConnectionError:
                progress_placeholder.empty()
                status_placeholder.empty()
                st.error("🔌 Cannot connect to backend. Ensure uvicorn is running on http://localhost:8000")
            except Exception as e:
                progress_placeholder.empty()
                status_placeholder.empty()
                st.error(f"❌ Unexpected error: {str(e)}")

# ============================================================================
# Preview and download section
# ============================================================================

if "generated" in st.session_state and st.session_state.generated:
    st.divider()
    st.header("📑 Results")
    if st.session_state.get("validation_message"):
        st.success(st.session_state.validation_message)

    job_id = st.session_state.job_id
    token_usage = st.session_state.token_usage

    # Token usage and cost
    st.subheader("💰 Token Usage & Cost Breakdown")

    # Top-level metrics
    col_t1, col_t2, col_t3 = st.columns(3)
    with col_t1:
        st.metric("Total Tokens", f"{token_usage['total_tokens']:,}")
    with col_t2:
        st.metric("Estimated Cost", f"${token_usage['estimated_cost_usd']:.6f}")
    with col_t3:
        model_display = token_usage.get('model_name', 'gemini-2.5-flash')
        st.metric("Model Used", model_display)

    # Detailed breakdown in expander
    with st.expander("📊 Detailed Token & Cost Breakdown", expanded=True):
        st.markdown("### Generation Attempts")
        col_att1, col_att2 = st.columns(2)
        with col_att1:
            st.info(f"**CV Generation:** {token_usage.get('cv_attempts', 1)} attempt(s)")
        with col_att2:
            st.info(f"**Cover Letter:** {token_usage.get('cl_attempts', 1)} attempt(s)")

        st.markdown("### Token Usage")

        # Create a breakdown table
        breakdown_data = {
            "Component": ["CV Input", "CV Output", "CL Input", "CL Output", "**Total**"],
            "Tokens": [
                f"{token_usage['cv_input_tokens']:,}",
                f"{token_usage['cv_output_tokens']:,}",
                f"{token_usage['cl_input_tokens']:,}",
                f"{token_usage['cl_output_tokens']:,}",
                f"**{token_usage['total_tokens']:,}**"
            ]
        }

        import pandas as pd
        df = pd.DataFrame(breakdown_data)
        st.table(df)

        st.markdown("### Cost Calculation")

        # Pricing comes from the single source of truth (D-4). This block used to hold
        # its own copy of the table, which had drifted: it still priced a model that
        # Phase 1 retired, and showed the user a figure the backend would not agree
        # with. It now reads the same module the backend prices with, so the breakdown
        # below and `estimated_cost_usd` cannot disagree.
        from services import pricing

        model_name = token_usage.get('model_name', 'gemini-2.5-flash')
        provider = token_usage.get('provider') or pricing.DEFAULT_PROVIDER

        total_input = token_usage['cv_input_tokens'] + token_usage['cl_input_tokens']
        total_output = token_usage['cv_output_tokens'] + token_usage['cl_output_tokens']

        # The per-call lines reuse the same function the backend charges with, so the
        # long-context tier (D-3) is reflected here rather than assumed away.
        input_cost = pricing.estimate_cost(total_input, 0, model_name, provider=provider)
        output_cost = pricing.estimate_cost(0, total_output, model_name, provider=provider)
        price = pricing.price_for(model_name, provider)
        tier = pricing.describe_tier(total_input, model_name, provider=provider)
        input_rate = price.input_long if tier == 'long-context' else price.input
        output_rate = price.output_long if tier == 'long-context' else price.output

        unpriced_note = (
            ''
            if pricing.is_priced(model_name, provider)
            else (
                f"\n\n⚠️ *{model_name} is not in the verified price table, so these "
                f"figures fall back to {pricing.DEFAULT_MODEL}'s rates. Treat them as "
                "an approximation.*"
            )
        )

        st.markdown(f"""
        - **Input tokens:** {total_input:,} × ${input_rate}/1M = **${input_cost:.6f}**
        - **Output tokens:** {total_output:,} × ${output_rate}/1M = **${output_cost:.6f}**
        - **Total cost:** **${token_usage['estimated_cost_usd']:.6f}**

        💡 *All costs are in USD. Pricing is for {model_name} via {provider} ({tier} tier).*
        {unpriced_note}
        """)

    st.divider()

    # Tailoring Explanation Section
    if "tailoring_explanation" in st.session_state and st.session_state.tailoring_explanation:
        with st.expander("📋 Tailoring Details & Changes Made", expanded=False):
            st.markdown("### How Your CV & Cover Letter Were Tailored")

            explanation = st.session_state.tailoring_explanation

            # Format structured explanation nicely
            if isinstance(explanation, dict):
                if explanation.get("summary_changes"):
                    st.markdown("**📝 Summary Changes:**")
                    st.write(explanation["summary_changes"])
                    st.markdown("")

                if explanation.get("bullet_modifications"):
                    st.markdown("**🔧 Bullet Modifications:**")
                    st.write(explanation["bullet_modifications"])
                    st.markdown("")

                if explanation.get("skill_reordering"):
                    st.markdown("**🔄 Skill Reordering:**")
                    st.write(explanation["skill_reordering"])
                    st.markdown("")

                if explanation.get("project_selection"):
                    st.markdown("**📂 Project Selection:**")
                    st.write(explanation["project_selection"])
                    st.markdown("")

                if explanation.get("overall_strategy"):
                    st.markdown("**🎯 Overall Strategy:**")
                    st.write(explanation["overall_strategy"])
            else:
                # Fallback for plain text
                st.markdown(str(explanation))

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
        st.subheader("???? Cover Letter Downloads")

        col_cl_docx, col_cl_pdf = st.columns(2)

        with col_cl_docx:
            try:
                cl_response = requests.get(
                    f"{API_DOWNLOAD_CL}/{job_id}",
                    timeout=30
                )
                if cl_response.status_code == 200:
                    st.download_button(
                        label="???? Download as DOCX",
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
            # Try the dedicated PDF endpoint
            try:
                cl_pdf_response = requests.get(
                    f"{API_DOWNLOAD_CL_PDF}/{job_id}",
                    timeout=30
                )
                if cl_pdf_response.status_code == 200:
                    st.download_button(
                        label="???? Download as PDF",
                        data=cl_pdf_response.content,
                        file_name=f"{job_id}_cover_letter.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
                else:
                    st.caption("(PDF not available)")
            except Exception:
                st.caption("(PDF not available)")

    st.divider()

    # New generation button
    if st.button("🔄 Generate Another", use_container_width=True):
        for key in ["generated", "job_id", "token_usage", "tailoring_explanation", "validation_message"]:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

else:
    # Empty state
    st.info(
        "👇 **Get started:** Paste a job description above and click 'Generate' to tailor your CV and cover letter!"
    )
