"""CV Tailor's Streamlit workspace; decisions and data access live in the bridge."""

from __future__ import annotations
import sys
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "backend", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from ui import services_bridge as bridge
from ui.review import render_application
from ui.theme import CSS

st.set_page_config(
    page_title="CV Tailor",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource(show_spinner=False)
def get_config():
    from config import Config

    return Config.from_env(env_file=ROOT / ".env", overrides={"project_root": ROOT})


def active_profile_id(config):
    return st.session_state.get("profile_id") or None


def clear_candidate_state():
    """Sidebar callback runs before page widgets, so resets are safe."""
    names = {
        "active_application",
        "generation_outcome",
        "search_outcome",
        "pending_handoff",
        "posting_provenance",
        "job_description",
        "company",
        "role",
        "work_country",
        "generation_model",
        "fresh_draft",
        "library_query",
        "library_status",
        "library_model",
        "library_page",
        "library_application",
        "setup_report",
    }
    for key in list(st.session_state):
        if key in names or str(key).startswith(("review_", "search_", "failed_")):
            del st.session_state[key]


def retain_inputs():
    """Detach saved values from widget cleanup when their page is not rendered."""
    names = {
        "job_description",
        "company",
        "role",
        "work_country",
        "generation_model",
        "fresh_draft",
        "library_query",
        "library_status",
        "library_model",
        "library_page",
        "library_application",
    }
    for key in list(st.session_state):
        if key in names or str(key).startswith(("search_", "review_")):
            st.session_state[key] = st.session_state[key]


def render_profile_picker(config, *, key="profile_picker"):
    options = bridge.list_profiles(config)
    if not options:
        st.warning(
            "No profiles in the store yet. Import a profile to get started; see Settings & help."
        )
        return None
    broken = [option for option in options if not option.is_usable]
    if broken:
        with st.expander(f"{len(broken)} profile(s) could not be read"):
            for option in broken:
                st.error(f"{option.profile_id} — {option.problem}")
    usable = [option for option in options if option.is_usable]
    if not usable:
        st.error("Every profile is unusable. Fix the YAML, then reload.")
        return None
    labels = {
        option.profile_id: f"{option.name} · {option.profile_id}" for option in usable
    }
    if key not in st.session_state:
        st.session_state[key] = bridge.initial_gui_profile(config, list(labels))
    elif st.session_state[key] is not None and st.session_state[key] not in labels:
        clear_candidate_state()
        st.session_state[key] = None
    chosen = st.selectbox(
        "Candidate",
        list(labels),
        index=None,
        placeholder="Choose a candidate",
        format_func=labels.get,
        key=key,
        on_change=clear_candidate_state,
        help="The only available profile is selected automatically. Otherwise your last valid choice is restored. Documents stay isolated by profile.",
    )
    if chosen:
        st.caption(f"Profile: {chosen}")
        if not bridge.remember_gui_profile(config, chosen):
            st.warning(
                "This profile is active, but the last choice could not be saved."
            )
    else:
        st.caption("Choose a candidate. Your last valid choice will be remembered.")
    return chosen


def require_profile(config, purpose):
    candidate = active_profile_id(config)
    if not candidate:
        st.info(f"Choose a candidate in the sidebar to {purpose}.")
        return None
    try:
        return bridge.load_profile(config, candidate)
    except Exception as error:
        st.error(f"Could not load {candidate}: {error}")
        return None


def render_header(config):
    if not active_profile_id(config):
        st.title("CV Tailor")
    candidate = active_profile_id(config)
    if candidate:
        profile = bridge.load_profile(config, candidate)
        with st.container(border=True):
            st.text(f"Active profile: {profile.identity.full_name} · {candidate}")
    st.caption(
        f"CV Tailor · configured model: {config.model} via {config.provider_name}"
    )


def page_generate(config):
    st.header("New application")
    profile = require_profile(config, "generate documents")
    if profile is None:
        return
    candidate = active_profile_id(config)
    actions = st.container()
    handoff = st.session_state.pop("pending_handoff", None)
    if handoff:
        countries = {
            "DE": "Germany",
            "AT": "Austria",
            "CH": "Switzerland",
            "IE": "Ireland",
            "NL": "Netherlands",
            "GB": "United Kingdom",
        }
        for key in ("job_description", "company", "role"):
            st.session_state[key] = handoff[key]
        st.session_state["work_country"] = countries.get(handoff["work_country"], "")
        st.session_state["posting_provenance"] = handoff["provenance"]
        st.session_state.pop("generation_outcome", None)
        st.session_state.pop("active_application", None)
    left, right = st.columns([3, 2], gap="large")
    with left:
        description = st.text_area(
            "Paste the full job description",
            height=250,
            key="job_description",
            placeholder="Responsibilities, requirements and company context…",
        )
        if description:
            st.caption(
                f"{len(description.split()):,} words · {len(description):,} characters"
            )
        if st.session_state.get("posting_provenance"):
            provenance = st.session_state["posting_provenance"]
            st.caption(f"Transferred from {provenance['source']} · {provenance['url']}")
            st.caption(
                "Check the full posting and country before generating. You can edit the text above."
            )
    with right:
        company = st.text_input("Company", key="company")
        role = st.text_input("Role title", key="role")
        country = st.selectbox(
            "Country of employment",
            [
                "",
                "Germany",
                "Ireland",
                "Netherlands",
                "United Kingdom",
                "Austria",
                "Switzerland",
                "Other",
            ],
            key="work_country",
            help="The job's actual country, not the employer's headquarters. Check work-authorisation wording yourself.",
        )
        catalogue = bridge.model_options(config)
        labels = {m.id: m.label for m in catalogue}
        selected = st.selectbox(
            "Model for this new application",
            ["", *labels],
            key="generation_model",
            format_func=lambda model: labels.get(model, "Use configured task routing"),
            help="Only the curated catalogue is offered. Saved applications retain their historical model.",
        )
        if selected:
            st.caption(next(m.guidance for m in catalogue if m.id == selected))
        elif len(catalogue) == 1:
            st.caption("The current curated catalogue contains one model.")
        fresh = st.checkbox(
            "Force a fresh draft",
            key="fresh_draft",
            help="An identical request normally reuses a validated result. A fresh draft makes paid calls.",
        )
    run_config = bridge.generation_config(config, selected)
    checks = bridge.preflight(run_config)
    with st.expander("Ready to generate? · configuration and task models"):
        st.write("Candidate:", profile.identity.full_name)
        st.write(
            "API key:",
            (
                "Configured; not verified with the provider"
                if checks["key_configured"]
                else "Missing"
            ),
        )
        st.write(
            "PDF engine:",
            "Available" if checks["pdf_engine"] else "Missing — see Settings & help",
        )
        st.table(
            [
                {"Task": task, "Requested model": model}
                for task, model in checks["models"].items()
            ]
        )
    with actions:
        generate = st.button(
            "Generate CV and cover letter",
            type="primary",
            use_container_width=True,
            disabled=not description.strip()
            or not checks["key_configured"]
            or not checks["pdf_engine"],
        )
        st.caption(
            "Paid generation · identical validated requests may reuse the cache. Review documents before sending."
        )
    if generate:
        with st.status("Preparing your application…", expanded=True) as progress:
            outcome = bridge.run_generation(
                run_config,
                candidate,
                description,
                company=company or None,
                role=role or None,
                work_country=country or None,
                use_cache=not fresh,
                status=lambda message: st.caption(message),
            )
            progress.update(
                label="Documents ready" if outcome.ok else "Generation failed",
                state="complete" if outcome.ok else "error",
                expanded=not outcome.ok,
            )
        st.session_state["generation_outcome"] = outcome
        if outcome.ok:
            st.session_state["active_application"] = outcome.job_id
            if st.session_state.get("posting_provenance"):
                try:
                    bridge.save_posting_provenance(
                        config,
                        candidate,
                        outcome.job_id,
                        st.session_state["posting_provenance"],
                    )
                except (OSError, ValueError):
                    st.warning(
                        "Documents were saved, but the posting-source metadata could not be saved."
                    )
    outcome = st.session_state.get("generation_outcome")
    if outcome and not outcome.ok:
        st.error(outcome.error)
        if outcome.drafts_saved:
            st.info(
                "Draft responses were saved. Review the partial attempt before paying for another draft; a usable document may not exist yet."
            )
        for job_id in outcome.details.get("applications", []):
            if st.button("Review saved attempt", key=f"failed_{candidate}_{job_id}"):
                st.session_state["active_application"] = job_id
    job_id = st.session_state.get("active_application")
    if job_id:
        st.divider()
        render_application(config, candidate, job_id)


def page_find_jobs(config, generate_target=None):
    st.header("Find jobs")
    st.caption("Free discovery and evidence-based matching. No model call.")
    if require_profile(config, "find jobs for your profile") is None:
        return
    with st.form("job_search"):
        columns = st.columns([3, 1, 1, 1])
        keywords = columns[0].text_input(
            "Keywords", key="search_keywords", placeholder="data engineer"
        )
        country = columns[1].text_input(
            "Country", key="search_country", placeholder="DE"
        )
        city = columns[2].text_input("City", key="search_city", placeholder="Berlin")
        limit = columns[3].number_input(
            "Max results",
            min_value=1,
            max_value=50,
            value=None if "search_limit" in st.session_state else 10,
            key="search_limit",
        )
        remote = st.checkbox("Remote only", key="search_remote")
        submitted = st.form_submit_button("Search", type="primary")
    with st.expander("Source coverage"):
        for source in bridge.source_coverage():
            st.text(source)
        st.caption(
            "Coverage is limited to configured sources and employer lists. This is not a search of every job board."
        )
    if submitted and limit is None:
        st.error("Enter a maximum result count between 1 and 50.")
    elif submitted:
        try:
            with st.spinner("Searching public sources…"):
                st.session_state["search_outcome"] = bridge.search_from_fields(
                    config,
                    active_profile_id(config),
                    keywords,
                    country,
                    city,
                    remote,
                    int(limit),
                )
        except Exception as error:
            st.session_state.pop("search_outcome", None)
            st.error(f"Search failed: {error}")
    outcome = st.session_state.get("search_outcome")
    if outcome is None:
        return
    for note in outcome.notes:
        st.caption(note)
    for name, message in outcome.failures.items():
        st.warning(f"Source {name}: {message}")
    if not outcome.results:
        st.info("No matching jobs. Try broader keywords or fewer location filters.")
        return
    st.caption(f"{len(outcome.results)} results · {outcome.jobs_read} postings read")
    for index, result in enumerate(outcome.results):
        job = result.job
        with st.container(border=True):
            title, signal = st.columns([4, 1])
            title.subheader(job.title)
            title.caption(
                " · ".join(
                    str(x) for x in [job.company, job.city.value, job.source] if x
                )
            )
            signal.metric("Matching signals", result.score)
            st.caption(
                f'Eligibility: {result.eligibility.value} · Published: {job.posted_at.date() if job.posted_at else "not stated"}'
            )
            for line in result.explanation():
                st.text(line)
            controls = st.columns(2)
            if job.url:
                controls[0].link_button("Open posting", job.url)
            if controls[1].button("Use this posting", key=f"search_use_{index}"):
                st.session_state["pending_handoff"] = bridge.posting_handoff(job)
                if generate_target is not None:
                    st.switch_page(generate_target)
            if not job.description:
                st.caption(
                    "No full description was provided. Paste it on New application before generating."
                )


def page_applications(config):
    st.header("Applications")
    if require_profile(config, "review saved applications") is None:
        return
    candidate = active_profile_id(config)
    applications = bridge.application_library(config, candidate)
    if not applications:
        st.info(
            "No saved applications for this candidate yet. Create one on New application."
        )
        return
    search, status, model = st.columns([3, 1, 2])
    query = search.text_input("Search company or role", key="library_query").casefold()
    status_filter = status.selectbox(
        "Status",
        ["All", *sorted({a["status"] for a in applications})],
        key="library_status",
    )
    model_names = sorted(
        {
            str(m)
            for a in applications
            for m in (a["manifest"].get("models") or {}).values()
        }
    )
    model_filter = model.selectbox(
        "Requested model", ["All", *model_names], key="library_model"
    )
    matches = [
        a
        for a in applications
        if query in f"{a['company']} {a['title']} {a['job_id']}".casefold()
        and (status_filter == "All" or a["status"] == status_filter)
        and (
            model_filter == "All"
            or model_filter in (a["manifest"].get("models") or {}).values()
        )
    ]
    st.caption(f"{len(matches)} of {len(applications)} saved applications")
    if not matches:
        st.info("No applications match these filters.")
        return
    pages = max(1, (len(matches) + 19) // 20)
    if st.session_state.get("library_page", 1) > pages:
        st.session_state["library_page"] = 1
    page = (
        st.selectbox("Page", list(range(1, pages + 1)), key="library_page")
        if pages > 1
        else 1
    )
    visible = matches[(page - 1) * 20 : page * 20]
    labels = {
        a[
            "job_id"
        ]: f"{a['company'] or 'Application'} · {a['title']} · {a['created_at'][:10]} · {a['status']}"
        for a in visible
    }
    if st.session_state.get("library_application") not in labels:
        st.session_state.pop("library_application", None)
    chosen = st.selectbox(
        "Review an application",
        list(labels),
        format_func=labels.get,
        key="library_application",
    )
    if chosen:
        render_application(config, candidate, chosen)


def page_about(config=None):
    config = config or get_config()
    st.header("Settings & help")
    st.subheader("Local setup")
    described = bridge.describe_configuration(config)
    st.markdown("**Profile store**")
    st.code(described["store"], language=None)
    st.write(f"{described['usable_profiles']} usable profile(s) available")
    st.write("Configured model:", described["model"])
    st.write("Provider:", described["provider"])
    if st.button("Run local setup checks", key="setup_checks"):
        st.session_state["setup_report"] = bridge.setup_checks(config)
    for check in st.session_state.get("setup_report", []):
        st.text(f"{check['status'].upper()} · {check['check']} · {check['detail']}")
        if check["fix"] and check["status"] != "ok":
            st.caption(check["fix"])
    if active_profile_id(config):
        profile = bridge.load_profile(config, active_profile_id(config))
        with st.expander("Selected profile · read-only summary"):
            st.write(profile.identity.full_name)
            st.write("Experience entries:", len(profile.experience))
            st.write("Skill groups:", ", ".join(profile.skills))
            st.caption(
                "Generation leaves your source profile unchanged. Maintain facts through the profile workflow."
            )
    st.markdown("""
**New application** — choose a candidate, paste a full posting, review the model and generate.
Generation may make paid calls. Cached generation and re-rendering existing text avoid new drafting calls.

**Review** — Documents shows PDFs and downloads. What changed compares the saved profile
with final CV text. Why these changes shows the model’s explanation. Run details keeps
historical usage separate from your current settings.

**Find jobs** — free public-source search. Matching signals count stated evidence; they are not a hiring probability.

**Privacy** — profiles and outputs live in your private store. Generation sends the profile
and posting to the configured model provider. Review saved files before sending them to an employer.

**Limits** — CV two pages; letter four paragraphs, 290–310 words. Automated checks cannot establish every claim or visual detail.
""")
    with st.expander("Command-line setup and recovery"):
        st.code(
            "cvtailor doctor\ncvtailor profile list\ncvtailor profile new <id>\ncvtailor profile import <path> --profile-id <id>"
        )
        st.caption(
            "Keys belong in your local .env, not in chat. Checks verify presence, not provider acceptance."
        )


def main():
    st.markdown(CSS, unsafe_allow_html=True)
    config = get_config()
    with st.sidebar:
        st.markdown("### cv tailor.")
        picked = render_profile_picker(config)
        st.session_state["profile_id"] = picked
        st.caption("Local workspace · private profile store")
    render_header(config)
    retain_inputs()

    def generate_page():
        page_generate(config)

    def find_jobs_page():
        page_find_jobs(config, generate_target)

    def applications_page():
        page_applications(config)

    def settings_page():
        page_about(config)

    generate_target = st.Page(
        generate_page,
        title="New application",
        icon="✍️",
        url_path="generate",
        default=True,
    )
    navigation = st.navigation(
        [
            generate_target,
            st.Page(find_jobs_page, title="Find jobs", icon="🔎", url_path="find-jobs"),
            st.Page(
                applications_page,
                title="Applications",
                icon="🗂️",
                url_path="applications",
            ),
            st.Page(settings_page, title="Settings & help", icon="⚙️", url_path="help"),
        ]
    )
    navigation.run()


if __name__ == "__main__":
    main()
