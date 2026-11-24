"""Shared application workspace, used after generation and in the library."""

import difflib
import html
from pathlib import Path
import re

import streamlit as st
from ui import services_bridge as bridge
from ui.answers import render_answers
from ui.layout_preview import render_layout_preview


def _document_label(name):
    path = Path(name)
    stem = path.stem.casefold()
    extension = path.suffix.lstrip(".").upper()
    if stem.endswith("_upload"):
        return f"CV for autofill · {extension}"
    if re.match(r"^\d{4}_cv_", stem):
        return f"CV · {extension}"
    if re.match(r"^\d{4}_cover_letter_", stem):
        return f"Cover letter · {extension}"
    return bridge.document_label(name)


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


def _primary_pdf(artifacts, saved_path, role):
    pdfs = [artifact for artifact in artifacts if artifact["kind"] == "pdf"]
    # Manifest paths from another computer still identify an artifact by its filename.
    if isinstance(saved_path, str):
        filename = re.split(r"[/\\]", saved_path)[-1]
        for artifact in pdfs:
            if artifact["name"] == filename:
                return artifact
    for artifact in pdfs:
        if _document_label(artifact["name"]) == f"{role} · PDF":
            return artifact
    return None


def _download(config, profile_id, job_id, artifact, *, prefix, label):
    name = artifact["name"]
    try:
        data = bridge.read_artifact(config, profile_id, job_id, name)
    except (OSError, ValueError) as error:
        st.warning(f"Could not read {name}: {error}")
        return
    st.download_button(
        label,
        data,
        file_name=name,
        mime=artifact["mime"],
        key=f"{prefix}_dl_{name}",
        on_click="ignore",
        width="stretch",
    )


def render_application(config, profile_id, job_id):
    try:
        detail = bridge.load_application(config, profile_id, job_id)
    except (OSError, ValueError) as error:
        st.error(str(error))
        return
    prefix = f"review_{profile_id}_{job_id}"
    manifest = detail["manifest"]
    artifacts = detail["artifacts"]
    title = " · ".join(filter(None, (detail["company"], detail["title"])))
    st.header(title)
    st.caption(f"{detail['status']} · {detail['created_at'][:10]}")
    primary_names = set()
    primary = (
        ("CV", manifest.get("cv_path"), "Download CV PDF"),
        ("Cover letter", manifest.get("cl_pdf_path"), "Download cover letter PDF"),
    )
    downloads = [
        (artifact, label)
        for role, saved_path, label in primary
        if (artifact := _primary_pdf(artifacts, saved_path, role))
    ]
    if downloads:
        columns = st.columns(len(downloads))
        for column, (artifact, label) in zip(columns, downloads):
            if artifact["name"] in primary_names:
                continue
            with column:
                _download(
                    config, profile_id, job_id, artifact, prefix=prefix, label=label
                )
            primary_names.add(artifact["name"])

    if manifest.get("status") == "failed":
        st.warning(manifest.get("error") or "Generation did not finish.")
    for warning in detail["warnings"]:
        st.warning(warning)
    _render_freshness(detail["artifact_freshness"])

    sections = {"documents": "Documents", "answers": "Answers", "details": "Details"}
    default = "answers" if detail["status"] == "Answers only" else "documents"
    requested = st.query_params.get("tab", default)
    tab_key = f"{prefix}_section"

    def select_section():
        selected = st.session_state[tab_key]
        if selected:
            st.query_params["tab"] = selected

    section = (
        st.radio(
            "Application section",
            options=list(sections),
            index=list(sections).index(requested if requested in sections else default),
            format_func=sections.get,
            key=tab_key,
            on_change=select_section,
            label_visibility="collapsed",
            horizontal=True,
        )
        or default
    )
    if section == "documents":
        _render_documents(config, profile_id, job_id, prefix, detail, primary_names)
    elif section == "answers":
        render_answers(config, profile_id, job_id, prefix, detail)
    else:
        _render_details(config, profile_id, job_id, detail)

    with st.expander("Application folder"):
        st.code(detail["path"], language=None, wrap_lines=True)


def _render_documents(config, profile_id, job_id, prefix, detail, primary_names):
    pdfs = sorted(
        (artifact for artifact in detail["artifacts"] if artifact["kind"] == "pdf"),
        key=lambda artifact: not _document_label(artifact["name"]).startswith("CV"),
    )
    if pdfs and st.checkbox("Show PDF preview", key=f"{prefix}_show_pdf"):
        chosen = st.selectbox(
            "Preview document",
            [artifact["name"] for artifact in pdfs],
            format_func=_document_label,
            key=f"preview_document_{profile_id}_{job_id}",
        )
        try:
            st.pdf(
                bridge.read_artifact(config, profile_id, job_id, chosen),
                height=560,
                key=f"{prefix}_{chosen}",
            )
        except Exception:
            st.info("PDF preview unavailable. Use the download to open the file.")
    elif not pdfs:
        st.info("This application has no saved PDFs.")

    render_layout_preview(config, profile_id, job_id, prefix, detail)

    with st.expander("More downloads and document checks"):
        if (
            detail["content"].get("cv") or detail["content"].get("tailored_cv")
        ) and st.button(
            "Create / refresh CV for autofill", key=f"{prefix}_export_upload"
        ):
            try:
                exporter = getattr(bridge, "export_upload_cv", None)
                if exporter is None:
                    from services.upload_cv import export_saved_upload_cv as exporter
                exporter(config, profile_id, job_id)
                detail = bridge.load_application(config, profile_id, job_id)
                st.success(
                    "Autofill DOCX and text created from saved content. No model call."
                )
            except (ValueError, OSError) as error:
                st.error(str(error))

        for artifact in detail["artifacts"]:
            if artifact["name"] not in primary_names:
                _download(
                    config,
                    profile_id,
                    job_id,
                    artifact,
                    prefix=prefix,
                    label=_document_label(artifact["name"]),
                )
        if not detail["artifacts"]:
            st.info("No downloadable documents were saved.")
        if not detail["content"]:
            st.info("Editable source is unavailable for this application.")

        if detail["word_layout"] and st.button(
            "Check Word pagination", key=f"{prefix}_check_word_layout"
        ):
            try:
                reports = bridge.check_word_layout(config, profile_id, job_id)
                detail = bridge.load_application(config, profile_id, job_id)
                st.success(
                    f"Word pagination check finished for {len(reports)} DOCX file(s). "
                    "This check uses LibreOffice when available."
                )
            except (OSError, ValueError) as error:
                st.warning(str(error))
        for name, check in detail["word_layout"].items():
            if check.get("status") == "current":
                report = check.get("report", {})
                if isinstance(report.get("page_count"), int):
                    st.caption(
                        f"{name}: {report['page_count']} page(s) · "
                        f"{report.get('engine') or 'pagination estimate'}"
                    )
                for warning in report.get("warnings", []):
                    st.caption(warning)
            elif check.get("status") == "stale":
                st.warning(f"{name}: saved Word pagination is stale.")
            else:
                st.caption(f"{name}: Word pagination has not been checked.")
        if pdfs:
            _render_pdf_checks(config, profile_id, job_id, prefix, detail)


def _render_freshness(freshness):
    stale = [name for name, info in freshness.items() if info.get("status") == "stale"]
    if stale:
        st.warning(
            "Saved documents may differ from the current source or rendering rules: "
            + ", ".join(stale)
        )
    unknown = [
        name for name, info in freshness.items() if info.get("status") == "unknown"
    ]
    if unknown:
        st.caption("Freshness could not be verified for " + ", ".join(unknown))


def _render_pdf_checks(config, profile_id, job_id, prefix, detail):
    cache_key = f"{prefix}_pdf_quality"
    fingerprint = detail.get("quality_fingerprint")
    revision = (detail["path"], fingerprint)
    cached_revision, reports = st.session_state.get(cache_key, (None, {}))
    if not fingerprint or cached_revision != revision:
        reports = {}
    if st.button("Check PDF text extraction", key=f"{prefix}_check_pdfs"):
        try:
            checked = bridge.load_application(
                config, profile_id, job_id, include_quality=True
            )
            reports = checked["document_quality"]
            if fingerprint and checked.get("quality_fingerprint") == fingerprint:
                st.session_state[cache_key] = (revision, reports)
            if not reports:
                st.info("No PDF text extraction results are available.")
        except (ValueError, OSError) as error:
            st.warning(str(error))
    if reports:
        _render_pdf_reports(reports)


def _render_pdf_reports(quality_reports):
    st.caption(
        "Two local PDF parsers compare extracted text with the saved source. "
        "Word retention is a text comparison, not an ATS score or screening guarantee."
    )
    for name, report in quality_reports.items():
        st.markdown(f"**{name}**")
        if report.get("page_count") is not None:
            st.caption(f"PDF pages: {report['page_count']}")
        layout = report.get("layout")
        if isinstance(layout, dict):
            preset = layout.get("preset", "custom")
            size = layout.get("body_size")
            st.caption(
                f"CV layout: {preset}"
                + (f" · {size:g}pt body" if isinstance(size, (int, float)) else "")
            )
            for page in layout.get("pages", []):
                fraction = page.get("used_height_fraction")
                if isinstance(fraction, (int, float)):
                    st.caption(
                        f"Page {page.get('page')}: {fraction:.0%} of printable height used"
                    )
            for warning in layout.get("warnings", []):
                st.caption(warning)
        for engine, result in report.get("engines", {}).items():
            retention = result.get("word_retention")
            retention_label = (
                f"{retention:.0%} source-word retention"
                if isinstance(retention, (int, float))
                else "Source-word retention unavailable"
            )
            status = result.get("status", "unknown")
            st.write(
                f"{engine}: {status} · {retention_label}"
                + (
                    f" · {len(result['missing_fields'])} expected field(s) missing"
                    if result.get("missing_fields")
                    else ""
                )
            )
            for warning in result.get("warnings", []):
                st.caption(warning)
        for warning in report.get("warnings", []):
            if warning not in {
                message
                for result in report.get("engines", {}).values()
                for message in result.get("warnings", [])
            }:
                st.caption(warning)


def _render_details(config, profile_id, job_id, detail):
    manifest = detail["manifest"]
    models = manifest.get("models") or {}
    usage = manifest.get("token_usage") or {}
    cost = usage.get("estimated_cost_usd")
    if isinstance(cost, (int, float)):
        st.caption(f"This run cost {cost:.6f} USD")
    if manifest.get("cv_page_count") is not None:
        st.caption(f"CV pages: {manifest['cv_page_count']}")
    if manifest.get("cover_letter_page_count") is not None:
        st.caption(f"Cover letter pages: {manifest['cover_letter_page_count']}")
    if detail["letter_words"] is not None:
        st.caption(f"Cover letter: {detail['letter_words']} body words")
    with st.expander("What changed"):
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
    with st.expander("Why these changes"):
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
    with st.expander("Run details"):
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
        with st.expander("Saved posting"):
            st.text(bridge.saved_posting(config, profile_id, job_id))
            if detail.get("posting_provenance"):
                st.json(detail["posting_provenance"])
            st.json(manifest)
