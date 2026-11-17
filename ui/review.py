"""Shared read-only application workspace, used after generation and in the library."""

import difflib
import html
import re

import streamlit as st
from ui import services_bridge as bridge


def highlighted(before, after):
    """Escaped word differences; neither profile nor model text becomes HTML."""
    old, new = re.split(r"(\s+)", before), re.split(r"(\s+)", after)
    left, right = [], []
    for tag, a, b, c, d in difflib.SequenceMatcher(
        None, old, new, autojunk=False
    ).get_opcodes():
        original, final = html.escape("".join(old[a:b])), html.escape("".join(new[c:d]))
        left.append(
            f"<del>{original}</del>" if tag in ("delete", "replace") else original
        )
        right.append(f"<ins>{final}</ins>" if tag in ("insert", "replace") else final)
    return "".join(left), "".join(right)


def render_application(config, profile_id, job_id):
    try:
        detail = bridge.load_application(config, profile_id, job_id)
    except (OSError, ValueError) as error:
        st.error(str(error))
        return
    prefix = f"review_{profile_id}_{job_id}"
    manifest = detail["manifest"]
    st.subheader(detail["title"])
    st.caption(
        " · ".join(
            filter(
                None, [detail["company"], detail["status"], detail["created_at"][:10]]
            )
        )
    )
    for warning in detail["warnings"]:
        st.warning(warning)
    columns = st.columns(4)
    models = manifest.get("models") if isinstance(manifest.get("models"), dict) else {}
    usage = (
        manifest.get("token_usage")
        if isinstance(manifest.get("token_usage"), dict)
        else {}
    )
    cost = usage.get("estimated_cost_usd")
    columns[0].metric(
        "Requested CV model", str(models.get("cv") or "Not recorded").split("/")[-1]
    )
    columns[1].metric("Run type", detail["run_type"])
    columns[2].metric(
        "This run cost",
        f"${cost:.6f}" if isinstance(cost, (int, float)) else "Not recorded",
    )
    columns[3].metric("CV pages", str(manifest.get("cv_page_count") or "Not recorded"))
    documents, changes, reasons, run = st.tabs(
        ["Documents", "What changed", "Why these changes", "Run details"]
    )
    with documents:
        left, right = st.columns([3, 1])
        artifacts = detail["artifacts"]
        with right:
            st.markdown("**Your documents**")
            for artifact in artifacts:
                try:
                    st.download_button(
                        bridge.document_label(artifact["name"]),
                        bridge.read_artifact(
                            config, profile_id, job_id, artifact["name"]
                        ),
                        file_name=artifact["name"],
                        mime=artifact["mime"],
                        key=f"{prefix}_dl_{artifact['name']}",
                        use_container_width=True,
                    )
                except OSError as error:
                    st.warning(f"Could not read document: {error}")
            if not artifacts:
                st.info("No downloadable documents were saved.")
            if manifest.get("cover_letter_page_count") is not None:
                st.caption(
                    f"Cover letter: {manifest['cover_letter_page_count']} page(s)"
                )
            if detail["letter_words"] is not None:
                st.caption(f"Cover letter: {detail['letter_words']} body words")
            if manifest.get("status") == "failed":
                st.warning(manifest.get("error") or "Generation did not finish.")
            st.caption(
                "Review names, dates, claims and layout before sending. Page checks do not replace your review."
            )
        with left:
            pdfs = sorted(
                [a for a in artifacts if a["kind"] == "pdf"],
                key=lambda a: not bridge.document_label(a["name"]).startswith("CV"),
            )
            if pdfs:
                chosen = st.selectbox(
                    "Preview document",
                    [a["name"] for a in pdfs],
                    format_func=bridge.document_label,
                    key=f"{prefix}_pdf",
                )
                try:
                    st.pdf(
                        bridge.read_artifact(config, profile_id, job_id, chosen),
                        height=680,
                        key=f"{prefix}_{chosen}",
                    )
                except Exception:
                    st.info(
                        "Preview unavailable in this environment. Use the document download."
                    )
            else:
                st.info("No PDF preview available for this application.")
        if not detail["content"]:
            st.info(
                "Editable source is unavailable for this older or incomplete application. Existing downloads still work."
            )
    with changes:
        st.caption(
            "Saved profile at generation time → final tailored CV. Highlighting shows text differences, not a quality score."
        )
        if not detail["comparison_available"]:
            st.info(
                "Comparison unavailable: a saved profile snapshot and editable CV are both required."
            )
        elif not detail["changes"]:
            st.info("No differences in the compared sections.")
        for index, change in enumerate(detail["changes"]):
            with st.expander(
                f"{change['kind']} · {change['section']}", expanded=index == 0
            ):
                old, new = highlighted(change["before"], change["after"])
                left, right = st.columns(2)
                with left:
                    st.caption("ORIGINAL · SAVED PROFILE")
                    st.markdown(
                        f'<div class="cv-before">{old or "No corresponding text"}</div>',
                        unsafe_allow_html=True,
                    )
                with right:
                    st.caption("TAILORED · FINAL CV")
                    st.markdown(
                        f'<div class="cv-after">{new or "No corresponding text"}</div>',
                        unsafe_allow_html=True,
                    )
        st.caption(
            "A newly written cover letter has no original counterpart. Roles match by employer, title and dates; projects by name. Renamed or consolidated projects can appear as separate source/final entries; no rename is inferred. Ambiguous matches are flagged."
        )
    with reasons:
        st.markdown("**Model explanation**")
        st.caption(
            "The model’s saved rationale. It may not explain every later layout edit; compare the final text yourself."
        )
        labels = {
            "overall_strategy": "Overall strategy",
            "summary_changes": "Summary wording",
            "bullet_modifications": "Experience and bullets",
            "skill_reordering": "Skill prioritisation",
            "project_selection": "Project selection",
        }
        if not detail["explanation"]:
            st.info(
                "No explanation was saved for this application. Viewing it does not make a new model call."
            )
        for key, label in labels.items():
            if detail["explanation"].get(key):
                with st.container(border=True):
                    st.markdown(f"**{label}**")
                    st.text(detail["explanation"][key])
    with run:
        st.caption(
            "Historical run data below comes from this application, not today’s configuration."
        )
        st.write("Provider:", manifest.get("provider") or "Not recorded")
        if models:
            st.table(
                [
                    {"Task": task, "Requested model": model}
                    for task, model in models.items()
                ]
            )
        else:
            st.info("Requested models were not recorded.")
        st.write("Run type:", detail["run_type"])
        st.write("Cost basis:", manifest.get("cost_source") or "Not recorded")
        st.write("Date:", detail["created_at"], f"({detail['date_source']})")
        if usage:
            st.table(
                [
                    {"Metric": key.replace("_", " "), "Value": str(value)}
                    for key, value in usage.items()
                ]
            )
        calls = manifest.get("calls") or []
        if calls:
            st.markdown("**Provider replies · this run**")
            st.dataframe(calls, use_container_width=True, hide_index=True)
            st.caption(
                "Reported model and request ID are values supplied by the provider. Missing fields remain unverified. Rows count received replies; internal transport retries are not itemised."
            )
        else:
            st.info(
                "No provider-reply records for this run. A requested model name alone is not provider confirmation."
            )
        if manifest.get("cache_hit"):
            with st.expander("Original cached generation · separate from this run"):
                st.json(
                    {
                        "usage": manifest.get("original_usage"),
                        "provider_replies": manifest.get("original_calls") or [],
                    }
                )
        with st.expander("Saved posting and storage location"):
            st.caption(detail["path"])
            st.text(bridge.saved_posting(config, profile_id, job_id))
            if detail.get("posting_provenance"):
                st.json(detail["posting_provenance"])
            st.json(manifest)
