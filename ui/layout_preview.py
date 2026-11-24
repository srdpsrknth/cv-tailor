"""On-demand page-break comparison in a saved application's Documents tab."""

import streamlit as st

from renderers import LaTeXRendererError
from services.application_layout_preview import (
    layout_source_revision,
    preview_saved_cv_layout,
    save_cv_layout_preview,
)


def _layout_row(label, layout):
    tails = layout.get("blank_tails_mm") or []
    return {
        "Layout": label,
        "Pages": layout["page_count"],
        "Blank space at page ends": " / ".join(f"{tail:.0f} mm" for tail in tails),
    }


def render_layout_preview(config, profile_id, job_id, prefix, detail):
    if not detail["content"].get("cv") or not detail["snapshot"]:
        return
    key = f"{prefix}_layout_preview"
    fingerprint = layout_source_revision(detail["content"], detail["snapshot"])
    cached = st.session_state.get(key)
    if cached and cached[0] != fingerprint:
        st.session_state.pop(key, None)
        cached = None

    with st.expander("Compare CV page breaks"):
        st.caption("Render a preview from the saved CV text without changing the saved PDF.")
        if st.button("Preview alternative CV layout", key=f"{key}_run"):
            try:
                with st.spinner("Comparing page breaks…"):
                    pdf, report = preview_saved_cv_layout(config, profile_id, job_id)
                cached = (report["source_revision"], pdf, report)
                st.session_state[key] = cached
            except (OSError, ValueError, LaTeXRendererError) as error:
                st.error(f"Could not render the layout preview. {error}")
        if cached:
            _, pdf, report = cached
            rows = [_layout_row("Preview", report)]
            if report.get("baseline"):
                rows.insert(0, _layout_row("Existing layout rules", report["baseline"]))
            st.table(rows)
            if st.button("Save preview to application folder", key=f"{key}_save"):
                try:
                    path = save_cv_layout_preview(config, profile_id, job_id, pdf, report)
                except (OSError, ValueError) as error:
                    st.error(f"Could not save the layout preview. {error}")
                else:
                    st.success(f"Saved {path.name} in the application folder.")
            try:
                st.pdf(pdf, height=560, key=f"{key}_pdf")
            except Exception:
                st.info("The PDF viewer is unavailable. Save the preview to open it locally.")
