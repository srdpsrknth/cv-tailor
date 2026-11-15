"""``cvtailor ui`` -- the Streamlit interface.

Rebuilt in Phase 6 onto :mod:`ui.services_bridge`, which owns every non-presentational
decision. This module is therefore only about *presentation*: layout, wording and
widget state. It contains no business rule, and it does not call an LLM, the
filesystem or the provider directly — everything goes through the bridge, so the
interface and the CLI cannot drift apart (the roadmap's acceptance criterion for
Phase 6).

Three things it fixes from the previous UI, each recorded because each was a real
defect rather than a stylistic preference:

**The candidate is chosen explicitly and fails closed** (ADR 0003). The old UI sent
no ``profile_id`` at all and worked only because this machine's ``.env`` happened to
set one, which meant a second candidate was unselectable and a machine without that
variable failed. Here the picker is populated from the store and an explicit choice
is required; a configured default is offered as a convenience, never relied upon.

**Cost is read from the shared pricing module.** The old UI kept its own copy of the
price table and it drifted — it still priced a model Phase 1 had retired and could
show a figure the backend disagreed with.

**Generation runs in-process**, not over HTTP. The API and the UI are both
interfaces over ``services.tailor_service``; the old UI was an HTTP client of the
backend, which added a failure mode (a second service that had to be running) and
no capability.

Run it with ``python scripts/start.py``, or directly:

    streamlit run ui/app.py --server.port 8501
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# The UI runs as a script, so the backend package is not importable by default.
# This mirrors what cli/context.py and the scripts do, and is the only sys.path
# manipulation in the file.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui import services_bridge as bridge  # noqa: E402

st.set_page_config(
    page_title="CV Tailor",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --- configuration and session state ------------------------------------------------------

@st.cache_resource(show_spinner=False)
def get_config():
    """Load configuration once per server process.

    ``Config.from_env`` is the only place the environment is read (ADR 0010), and it
    is cached so a page interaction does not re-read ``.env`` on every rerun.
    """
    from config import Config

    return Config.from_env(env_file=ROOT / ".env", overrides={"project_root": ROOT})


def active_profile_id(config):
    """The candidate this session is acting for, or ``None``.

    Session state is the only source. It is deliberately **not** seeded from the
    configured default: doing so would present a preset that a user could mistake
    for a considered choice, and ADR 0003 exists precisely to stop a candidate being
    selected without someone deciding. The picker offers the configured value as the
    first option, so choosing it is one click and still an explicit act.
    """
    return st.session_state.get("profile_id") or None


def remember(result_key, value) -> None:
    st.session_state[result_key] = value


# --- shared pieces ------------------------------------------------------------------------

def render_header(config) -> None:
    """A quiet status strip: what this install is pointed at, and nothing more."""
    described = bridge.describe_configuration(config)
    with st.container(border=True):
        left, middle, right = st.columns([2, 2, 3])
        with left:
            st.caption("PROFILE STORE")
            st.code(described["store"], language=None)
        with middle:
            st.caption("CANDIDATES")
            st.markdown(f"**{described['usable_profiles']}** available")
        with right:
            st.caption("MODEL")
            st.markdown(f"`{described['model'] or 'not configured'}`")
            if described["provider"]:
                st.caption(f"via {described['provider']}")


def render_profile_picker(config, *, key: str = "profile_picker") -> str | None:
    """Choose the candidate. Returns the id, or ``None`` when none can be chosen.

    Fails closed: with no profiles, or none usable, this explains the situation and
    returns ``None`` so the caller can stop, rather than proceeding without a
    candidate.
    """
    options = bridge.list_profiles(config)
    if not options:
        st.warning(
            "No profiles in the store yet. Create one with "
            "`cvtailor profile new <id>`, or import an existing `profile.yaml` with "
            "`cvtailor profile import <path> --profile-id <id>`."
        )
        return None

    usable = [option for option in options if option.is_usable]
    broken = [option for option in options if not option.is_usable]
    if broken:
        with st.expander(f"⚠️ {len(broken)} profile(s) could not be read", expanded=False):
            for option in broken:
                st.error(f"**{option.profile_id}** — {option.problem}")

    if not usable:
        st.error("Every profile in the store is unusable. Fix the YAML above, then reload.")
        return None

    configured = getattr(config, "profile_id", None)
    ids = [option.profile_id for option in usable]
    default_index = ids.index(configured) if configured in ids else 0

    labels = {option.profile_id: option.label() for option in usable}
    chosen = st.selectbox(
        "Which candidate are you generating for?",
        options=ids,
        index=default_index,
        format_func=lambda value: labels.get(value, value),
        key=key,
        help=(
            "CV Tailor never picks a profile for you — the documents are filed under "
            "this id, so an unnoticed default is how the wrong person's CV gets sent."
        ),
    )
    if len(usable) == 1:
        st.caption(
            "You still have to choose even with one profile: the choice is what files "
            "the documents, and a silent default is the failure this prevents."
        )
    return chosen


# --- pages --------------------------------------------------------------------------------
#
# Defined before the navigation is built, because st.Page takes the callables and a
# Streamlit script is executed top to bottom on every interaction. Each page takes the
# cached config explicitly rather than closing over a module-level global, so the pages
# stay importable and testable on their own.


def require_profile(config, purpose: str):
    """Load the active profile, or stop the page with an explanation.

    Returns the profile, or ``None`` after rendering why it cannot proceed. Every
    page calls this, so no page can accidentally act without a candidate.
    """
    profile_id = active_profile_id(config)
    if not profile_id:
        st.info(
            f"Choose a candidate in the sidebar to {purpose}. "
            "Every command that touches a candidate's data requires one (ADR 0003)."
        )
        return None
    try:
        return bridge.load_profile(config, profile_id)
    except Exception as error:  # noqa: BLE001 - shown, not raised
        st.error(f"Could not load **{profile_id}**: {error}")
        return None


def page_generate(config) -> None:
    st.subheader("Generate documents for a posting")
    profile = require_profile(config, "generate documents")
    if profile is None:
        return

    profile_id = active_profile_id(config)

    left, right = st.columns([3, 2], gap="large")

    with left:
        job_description = st.text_area(
            "Paste the full job description",
            height=320,
            placeholder=(
                "Paste everything: responsibilities, requirements, the lot.\n\n"
                "Include the job URL and today's date at the top if you have them — "
                "it makes the saved record easier to trace later."
            ),
            key="job_description",
        )

    with right:
        st.markdown("**Optional details**")
        st.caption("Leave blank to let the posting decide. They mostly improve framing.")
        company = st.text_input("Company", key="company",
                                placeholder="Northwind Analytics GmbH")
        role = st.text_input("Role title", key="role", placeholder="Analytical Engineer")
        work_country = st.selectbox(
            "Country of employment",
            options=["", "Germany", "Ireland", "Netherlands", "United Kingdom",
                     "Austria", "Switzerland", "Other"],
            key="work_country",
            help=(
                "The country the job is actually in, not the employer's headquarters. "
                "This decides the work-authorisation wording, so it is worth setting."
            ),
        )
        use_cache = not st.checkbox(
            "Force a fresh draft",
            value=False,
            help="By default an identical job and profile reuses the stored result and costs nothing.",
        )
        words = len(job_description.split())
        if job_description.strip():
            st.caption(f"{words:,} words pasted")

    generate = st.button(
        "Generate CV and cover letter",
        type="primary",
        use_container_width=True,
        disabled=not job_description.strip(),
    )

    if not generate:
        return

    # A generation run takes a minute or more and makes several network calls. It is
    # the one operation here that costs money, so it reports progress and never runs
    # silently.
    progress_lines: list[str] = []
    with st.status("Generating… this costs about $0.003", expanded=True) as status:
        progress_box = st.empty()

        def on_status(message: str) -> None:
            progress_lines.append(message)
            progress_box.caption(" → ".join(progress_lines[-3:]))

        outcome = bridge.run_generation(
            config,
            profile_id,
            job_description,
            company=company or None,
            role=role or None,
            work_country=work_country or None,
            use_cache=use_cache,
            status=on_status,
        )

        if outcome.ok:
            status.update(label="Done", state="complete", expanded=False)
        else:
            status.update(label="Generation failed", state="error", expanded=True)

    if not outcome.ok:
        st.error(outcome.error)
        st.info(
            "The editable drafts are usually still saved even when validation failed. "
            "Check the Applications page for the folder before regenerating — a retry "
            "costs money."
        )
        return

    st.success(f"Generated **{outcome.job_id}**")
    for line in outcome.summary:
        st.write(f"- {line}")
    st.session_state["last_job_id"] = outcome.job_id
    st.session_state["last_job_folder"] = str(outcome.job_folder) if outcome.job_folder else None
    st.toast("Documents ready", icon="✅")

    render_result(config, profile_id, outcome.job_id, outcome.job_folder)


def render_result(config, profile_id: str, job_id: str, folder) -> None:
    """Downloads and a reminder to read the documents."""
    artifacts = bridge.list_artifacts(folder)
    st.divider()
    st.subheader("📑 Your documents")

    if not artifacts:
        st.warning(f"No files found in {folder}. The generation may not have finished.")
        return

    pdfs = [a for a in artifacts if a["kind"] == "pdf"]
    docs = [a for a in artifacts if a["kind"] == "docx"]

    columns = st.columns(max(len(pdfs) + len(docs), 1))
    for column, artifact in zip(columns, pdfs + docs):
        with column:
            with st.container(border=True):
                st.markdown(f"**{artifact['name']}**")
                st.caption(f"{artifact['size_kb']} KB · {artifact['kind'].upper()}")
                try:
                    st.download_button(
                        "Download",
                        data=Path(artifact["path"]).read_bytes(),
                        file_name=artifact["name"],
                        mime=artifact["mime"],
                        key=f"dl_{job_id}_{artifact['name']}",
                        use_container_width=True,
                    )
                except OSError as error:
                    st.error(f"Could not read the file: {error}")

    st.info(
        "**Read both documents before sending them.** The tool checks page count and "
        "word count, and the test suite checks for clipped text and orphan headings — "
        "but nothing automated reads them the way a recruiter will. Check employer "
        "names, dates, and that nothing is claimed you cannot back up in an interview."
    )
    st.caption(f"Saved in `{folder}`")


def page_find_jobs(config) -> None:
    """Search public job sources. Free: no API key, no LLM call."""
    st.subheader("Find jobs")
    st.caption(
        "Searches public job sources and ranks what comes back. **Free** — no API key "
        "and no AI call."
    )

    with st.form("job_search"):
        row = st.columns([3, 1, 1, 1])
        with row[0]:
            keywords = st.text_input("Keywords", placeholder="data engineer")
        with row[1]:
            country = st.text_input("Country", placeholder="DE")
        with row[2]:
            city = st.text_input("City", placeholder="Berlin")
        with row[3]:
            limit = st.number_input("Max results", min_value=1, max_value=50, value=10)
        remote_only = st.checkbox("Remote only")
        submitted = st.form_submit_button("Search", type="primary")

    if not submitted:
        st.caption(
            "Sources are configured in `SAMPLE_*` constants in "
            "`backend/services/job_connectors.py`; add your own employers there."
        )
        return

    from models.job import SearchQuery
    from services.job_connectors import build_default_sources
    from services.job_match import MatchPreferences

    profile = require_profile(config, "rank jobs against your profile")
    if profile is None:
        return

    profile_id = active_profile_id(config)
    query = SearchQuery(
        keywords=keywords or None,
        country=country or None,
        city=city or None,
        remote=True if remote_only else None,
        limit=int(limit),
    )
    preferences = MatchPreferences.from_profile(
        profile, keywords=tuple(keywords.split()) if keywords else ()
    )

    with st.spinner("Searching…"):
        outcome = bridge.run_job_search(
            config, profile_id, query, preferences=preferences,
            sources=build_default_sources(),
        )

    for note in outcome.notes:
        st.caption(f"ℹ️ {note}")
    for name, message in outcome.failures.items():
        st.warning(f"Source **{name}** failed: {message}")

    if not outcome.results:
        st.info("No matching jobs. Try a broader keyword, or drop the country/city filter.")
        return

    st.success(f"{len(outcome.results)} match(es) from {outcome.jobs_read} posting(s) read.")
    for result in outcome.results:
        job = result.job
        with st.container(border=True):
            head = st.columns([5, 1])
            with head[0]:
                st.markdown(f"**{job.title}**")
                where = job.city.value or (job.country.value if job.country.is_verified else "")
                meta = " · ".join(filter(None, [job.company, where, job.source]))
                st.caption(meta)
            with head[1]:
                st.metric("Match", result.score)
            for line in result.explanation():
                st.caption(f"• {line}")
            if job.url:
                st.link_button("Open posting", job.url)


def page_applications(config) -> None:
    """Everything already generated, for this candidate."""
    st.subheader("Applications")
    profile = require_profile(config, "see your applications")
    if profile is None:
        return

    profile_id = active_profile_id(config)
    applications = bridge.list_applications(config, profile_id)

    if not applications:
        st.info(
            "Nothing generated yet for this candidate. Use the **Generate** page, or "
            "the CLI. Applications produced either way appear here — they share one store."
        )
        return

    st.caption(f"{len(applications)} application(s) for **{profile_id}**")
    for application in applications:
        with st.expander(application["job_id"], expanded=False):
            if not application["has_content"]:
                st.warning(
                    "No `source/content.json` — this folder has no editable text, so it "
                    "cannot be re-rendered. It may be an older or partial run."
                )
            if not application["artifacts"]:
                st.caption("No downloadable files in this folder.")
                continue
            columns = st.columns(len(application["artifacts"]))
            for column, artifact in zip(columns, application["artifacts"]):
                with column:
                    st.caption(f"{artifact['name']} ({artifact['size_kb']} KB)")
                    try:
                        st.download_button(
                            "Download",
                            data=Path(artifact["path"]).read_bytes(),
                            file_name=artifact["name"],
                            mime=artifact["mime"],
                            key=f"app_{application['job_id']}_{artifact['name']}",
                        )
                    except OSError as error:
                        st.error(str(error))
            st.caption(f"`{application['path']}`")


def page_about() -> None:
    st.subheader("How to use this")
    st.markdown(
        """
        **Generate** — paste a posting, choose a candidate, generate. Costs roughly
        **$0.003** on the default model: one CV call and one cover-letter call.

        **Find jobs** — searches public job boards and ranks results against your
        profile. Free.

        **Applications** — everything already generated, with downloads. Re-rendering
        an existing application after editing its `content.json` is free.

        ### The rules this tool will not break

        - **It never picks a profile for you.** No default, no "the only one".
        - **Your data stays outside this repository.** Profiles, applications and
          documents live in the private store shown at the top of every page.
        - **It does not invent facts.** It tailors wording and emphasis from your real
          profile; it will not add a skill or employer you do not have.
        - **Default limits:** CV two pages, cover letter four paragraphs, 290–310 words.

        ### Something wrong?

        Run `cvtailor doctor` in a terminal — it checks Python, the store, the profile,
        LaTeX and the API key, and tells you the fix. The command line is the
        supported path for anything that breaks here.
        """
    )


# --- run ----------------------------------------------------------------------------------

def main() -> None:
    """Draw the shell and dispatch to the selected page."""
    st.title("📄 CV Tailor")
    st.caption(
        "Tailor a CV and cover letter to a real posting, and find postings worth "
        "applying to."
    )

    config = get_config()
    render_header(config)

    with st.sidebar:
        st.header("Candidate")
        picked = render_profile_picker(config)
        if picked:
            st.session_state["profile_id"] = picked
        st.divider()
        st.caption(
            "The command line does everything this interface does. "
            "Run `cvtailor` with no arguments for a guided menu."
        )

    st.divider()

    config = get_config()

    # st.navigation derives a page's URL path from the callable's name, so passing
    # lambdas makes every page collide on "<lambda>" and raises StreamlitAPIException.
    # Named wrappers with an explicit url_path avoid that, and give readable URLs.
    def generate_page() -> None:
        page_generate(config)

    def find_jobs_page() -> None:
        page_find_jobs(config)

    def applications_page() -> None:
        page_applications(config)

    navigation = st.navigation(
        [
            st.Page(generate_page, title="Generate", icon="✍️", url_path="generate",
                    default=True),
            st.Page(find_jobs_page, title="Find jobs", icon="🔎", url_path="find-jobs"),
            st.Page(applications_page, title="Applications", icon="🗂️",
                    url_path="applications"),
            st.Page(page_about, title="Help", icon="❓", url_path="help"),
        ]
    )
    navigation.run()


main()
