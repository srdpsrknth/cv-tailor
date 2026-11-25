"""Standalone projects the model may tailor, and the richer CV sections (WP5/WP6).

Every new profile field is optional: the first group pins that a profile which uses none
of them is byte-for-byte what it was before.
"""
import json
from pathlib import Path

import pytest
from docx import Document
from pydantic import ValidationError
from pypdf import PdfReader

from models.profile import Profile
from models.tailored_output import TailoredCV
from renderers.cv_layout import PRESETS
from renderers.latex_renderer import LaTeXRenderer
from renderers.upload_cv import render_upload_cv
from services import prompts, validation
from services.application_review import _expected_cv_text
from services.cache_store import serialize_profile_bytes
from services.cv_delta import apply_cv_delta, looks_like_cv_delta
from services.pipeline import DocumentGenerator
from services.response_schemas import RESPONSE_SCHEMAS
from services.validation import ProfileRules, profile_facts_json, validate_cv
from support import OfflineGemini, latex_available, read_json


def with_profile(profile, **changes):
    """A copy of ``profile`` with top-level fields replaced, re-validated."""
    return Profile.model_validate({**json.loads(profile.model_dump_json()), **changes})


PROJECTS = [
    {"name": "Transit Map", "bullets": [
        "Mapped 12 public transport gaps with open data.",
        "Published the findings as an interactive dashboard."],
     "dates": "2024", "technologies": ["Python", "Leaflet"], "context": "University team project"},
    {"name": "Weather Archive", "bullets": ["Catalogued public weather records."]},
]

FULL = {
    "standalone_projects": PROJECTS,
    "publications": [
        "A. Sample (2025). Transit & Access. Example Journal.",
        {"text": "A. Sample (2024). Second Paper. Example Press.",
         "bullets": ["Peer-reviewed by two referees."]},
    ],
    "activities": [{"text": "Volunteer mentor, Community Data Club.",
                    "bullets": ["Ran monthly SQL clinics."]}],
    "certifications": ["Plain Certificate", {"name": "Structured Certificate", "issuer": "Example Body", "year": 2024}],
}


@pytest.fixture
def rich_profile(analyst_profile):
    data = json.loads(analyst_profile.model_dump_json())
    data["education"][0]["highlights"] = ["Thesis: Synthetic Forecasting", "Focus: causal inference"]
    data["experience"][2]["optional"] = True
    data["experience"][0]["display_name"] = "Northwind"
    return Profile.model_validate({**data, **FULL})


def base_cv(**changes):
    cv = TailoredCV.model_validate(read_json("content", "valid_content.json")["cv"])
    return rebuilt(cv, **changes)


def rebuilt(cv, **changes):
    """``model_copy`` does not validate, so dict-form projects must go through here."""
    return TailoredCV.model_validate({**cv.model_dump(), **changes})


# --- backward compatibility ---------------------------------------------------------

NEW_KEYS = {"dates", "context", "highlights", "optional", "display_name", "standalone_projects_policy"}


def _keys(node):
    if isinstance(node, dict):
        yield from node
        for value in node.values():
            yield from _keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _keys(value)


def test_a_profile_using_none_of_the_new_fields_serialises_as_before(analyst_profile):
    dumped = analyst_profile.model_dump()
    assert not NEW_KEYS & set(_keys(dumped))
    assert not NEW_KEYS & set(_keys(json.loads(serialize_profile_bytes(analyst_profile))))
    assert not NEW_KEYS & set(_keys(json.loads(profile_facts_json(analyst_profile))))
    assert Profile.model_validate(dumped) == analyst_profile


@pytest.mark.parametrize("path", sorted(Path(__file__).parent.joinpath("fixtures/profiles").glob("synthetic_*.yaml")))
def test_existing_synthetic_profiles_still_load(path):
    import yaml
    profile = Profile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert profile.standalone_projects_policy == "select"


@pytest.mark.parametrize("change", [
    lambda d: d["standalone_projects"].append({"name": "X", "bullets": [], "dates": "2025"}) or d,
    lambda d: d["education"][0].update(highlights=["Thesis"]) or d,
    lambda d: d["experience"][0].update(optional=True) or d,
    lambda d: d["experience"][0].update(display_name="Short") or d,
    lambda d: d.update(standalone_projects_policy="all") or d,
    lambda d: d.update(certifications=[{"name": "C", "issuer": "I"}]) or d,
    lambda d: d.update(publications=[{"text": "P", "bullets": ["b"]}]) or d,
])
def test_each_new_field_changes_the_cache_key_and_the_facts(analyst_profile, change):
    from services.cache_store import cache_key
    changed = Profile.model_validate(change(json.loads(analyst_profile.model_dump_json())))
    assert serialize_profile_bytes(changed) != serialize_profile_bytes(analyst_profile)
    assert profile_facts_json(changed) != profile_facts_json(analyst_profile)
    keys = [cache_key(profile_bytes=serialize_profile_bytes(p), job_description="jd", company_name="C",
                      role_title="R", work_country=None, prompt_cv="a", prompt_cl="b",
                      **{k: "x" for k in _remaining_key_args()})
            for p in (analyst_profile, changed)]
    assert keys[0] != keys[1]


def _remaining_key_args():
    import inspect
    from services.cache_store import cache_key
    done = {"profile_bytes", "job_description", "company_name", "role_title", "work_country",
            "prompt_cv", "prompt_cl"}
    return [n for n in inspect.signature(cache_key).parameters if n not in done]


def test_new_fields_reject_unknown_siblings(analyst_profile):
    with pytest.raises(ValidationError):
        with_profile(analyst_profile, certifications=[{"name": "C", "bogus": 1}])
    with pytest.raises(ValidationError):
        with_profile(analyst_profile, publications=[{"text": "P", "bogus": 1}])
    with pytest.raises(ValidationError):
        with_profile(analyst_profile, standalone_projects_policy="some")


# --- standalone projects: validation --------------------------------------------------

@pytest.fixture
def project_profile(analyst_profile):
    return with_profile(analyst_profile, standalone_projects=PROJECTS)


def check(cv, profile):
    validate_cv(cv, profile, ProfileRules.from_profile(profile))


def obj(name, bullets):
    return {"name": name, "bullets": bullets}


def test_names_and_objects_are_both_accepted(project_profile):
    cv = base_cv(standalone_projects=["Weather Archive", obj("Transit Map", ["Mapped public transport gaps."])])
    check(cv, project_profile)
    resolved = cv.resolve_standalone_projects(project_profile)
    assert [p.name for p in resolved] == ["Weather Archive", "Transit Map"]
    assert resolved[0].bullets == ["Catalogued public weather records."]
    assert resolved[1].bullets == ["Mapped public transport gaps."]
    # Metadata always comes from the profile, never from the model.
    assert resolved[1].context == "University team project" and resolved[1].dates == "2024"
    assert TailoredCV.model_validate_json(cv.model_dump_json()) == cv


@pytest.mark.parametrize("item, message", [
    (obj("Made-up", ["Something."]), "distinct standalone project names"),
    (obj("Transit Map", []), "between 1 and 3"),
    (obj("Transit Map", ["a", "b", "c", "d"]), "between 1 and 3"),
    (obj("Transit Map", ["a", "  "]), "between 1 and 3"),
    (obj("Transit Map", ["Mapped 99 gaps."]), "do not add metrics"),
    (obj("Transit Map", ["Mapped public transport gaps with Kubernetes."]), "Do not claim Kubernetes"),
    (obj("Transit Map", ["Mapped gaps with no direct experience in maps."]), "gap statement"),
])
def test_reworded_bullets_face_the_same_gates_as_employer_bullets(project_profile, item, message):
    profile = with_profile(project_profile, rules={"banned_tools": ["Kubernetes"]})
    with pytest.raises(ValueError, match=message):
        check(base_cv(standalone_projects=[item]), profile)


def test_a_number_the_profile_states_may_be_reused(project_profile):
    check(base_cv(standalone_projects=[obj("Transit Map", ["Found 12 gaps in public transport."])]), project_profile)


def test_a_project_with_no_profile_bullets_cannot_be_reworded(analyst_profile):
    profile = with_profile(analyst_profile, standalone_projects=[{"name": "Bare"}])
    with pytest.raises(ValueError, match="select it by name only"):
        check(base_cv(standalone_projects=[obj("Bare", ["Invented work."])]), profile)
    check(base_cv(standalone_projects=["Bare"]), profile)


def test_policy_all_requires_every_project_in_profile_order(analyst_profile):
    profile = with_profile(analyst_profile, standalone_projects=PROJECTS, standalone_projects_policy="all")
    check(base_cv(standalone_projects=["Transit Map", obj("Weather Archive", ["Records, catalogued."])]), profile)
    for selection in ([], ["Transit Map"], ["Weather Archive", "Transit Map"]):
        with pytest.raises(ValueError, match="policy is 'all'"):
            check(base_cv(standalone_projects=selection), profile)
    # The default policy still lets the model choose.
    check(base_cv(standalone_projects=[]), with_profile(analyst_profile, standalone_projects=PROJECTS))


# --- optional roles -----------------------------------------------------------------

def test_an_optional_role_may_be_omitted_but_a_required_one_may_not(analyst_profile):
    data = json.loads(analyst_profile.model_dump_json())
    data["experience"][2]["optional"] = True
    profile = Profile.model_validate(data)
    cv = base_cv()
    check(cv, analyst_profile)
    shorter = cv.model_copy(update={"experience": cv.experience[:2]})
    check(shorter, profile)
    with pytest.raises(ValueError, match="only roles the profile marks optional"):
        check(shorter, analyst_profile)
    with pytest.raises(ValueError, match="only roles the profile marks optional"):
        check(cv.model_copy(update={"experience": cv.experience[1:]}), profile)
    with pytest.raises(ValueError, match="only roles the profile marks optional"):
        check(cv.model_copy(update={"experience": cv.experience + cv.experience[:1]}), profile)


# --- prompts, schema, retries ---------------------------------------------------------

def test_the_context_states_the_all_policy_only_when_it_applies(analyst_profile):
    profile = with_profile(analyst_profile, standalone_projects=PROJECTS)
    assert "STANDALONE PROJECTS POLICY" not in prompts.build_context("jd", profile)
    assert "STANDALONE PROJECTS POLICY: all" in prompts.build_context(
        "jd", with_profile(profile, standalone_projects_policy="all"))
    # A profile with no standalone projects has nothing to say.
    assert "STANDALONE PROJECTS POLICY" not in prompts.build_context(
        "jd", with_profile(analyst_profile, standalone_projects_policy="all"))


def test_the_prompt_allows_rewording_only_from_the_projects_own_facts():
    text = prompts.PROMPT_CV_PATH.read_text(encoding="utf-8")
    for needle in ('"bullets"', "do not add tools, metrics", "optional", "policy is \"all\""):
        assert needle in text


def test_the_schema_accepts_a_name_or_an_object():
    items = RESPONSE_SCHEMAS["cv"]["properties"]["cv"]["properties"]["standalone_projects"]["items"]
    kinds = items["anyOf"]
    assert {"type": "string"} in kinds
    objects = [k for k in kinds if k.get("type") == "object"]
    assert len(objects) == 1
    assert objects[0]["additionalProperties"] is False
    assert sorted(objects[0]["required"]) == ["bullets", "name"]
    assert "any_of" not in json.dumps(RESPONSE_SCHEMAS["cv"])


def test_a_retry_may_shorten_reworded_bullets_but_not_drop_a_project(project_profile):
    cv = base_cv(standalone_projects=["Weather Archive", obj("Transit Map", ["Mapped gaps.", "Built a dashboard."])])
    delta = {"standalone_projects[1].bullets": ["Mapped gaps."]}
    assert looks_like_cv_delta(delta)
    assert apply_cv_delta(cv, delta).standalone_projects[1].bullets == ["Mapped gaps."]
    assert apply_cv_delta(cv, {"standalone_projects[1].bullets[1]": "Dashboard."}
                          ).standalone_projects[1].bullets[1] == "Dashboard."
    assert cv.standalone_projects[1].bullets[0] == "Mapped gaps."  # the input is untouched
    for bad in ({"standalone_projects[0].bullets": ["x"]},       # selected by name
                {"standalone_projects[5].bullets": ["x"]},       # no such project
                {"standalone_projects": []},                       # not addressable
                {"standalone_projects[1].name": "Other"}):
        with pytest.raises(ValueError):
            apply_cv_delta(cv, bad)


def test_the_retry_brief_names_the_policy_and_the_shortenable_projects(project_profile):
    cv = base_cv(standalone_projects=["Weather Archive", obj("Transit Map", ["Mapped gaps."])])
    text = prompts.layout_retry_instruction(cv, 3, 600, 0, ProfileRules(), standalone_policy="all")
    assert "never drop a project" in text and "requires every standalone project" in text
    assert "standalone_projects[1]" in text and "standalone_projects[0]" not in text
    plain = prompts.layout_retry_instruction(base_cv(standalone_projects=["Weather Archive"]), 3, 600, 0, ProfileRules())
    assert "Leave them unchanged" in plain and "requires every" not in plain
    assert "standalone_projects" not in prompts.layout_retry_instruction(base_cv(), 3, 600, 0, ProfileRules())


def test_a_layout_retry_cannot_drop_a_project_under_the_all_policy(analyst_profile):
    profile = with_profile(analyst_profile, standalone_projects=PROJECTS, standalone_projects_policy="all")
    cv = base_cv(standalone_projects=["Transit Map", "Weather Archive"])
    dropped = {"cv": rebuilt(cv, standalone_projects=["Transit Map"]).model_dump()}
    with pytest.raises(ValueError, match="Keep the same|standalone"):
        DocumentGenerator(OfflineGemini([json.dumps(dropped)] * 3), profile).generate("retry", "cv", base_cv=cv)
    reworded = {"cv": rebuilt(cv, standalone_projects=[
        obj("Transit Map", ["Mapped public transport gaps."]), "Weather Archive"]).model_dump()}
    result, _ = DocumentGenerator(OfflineGemini([json.dumps(reworded)]), profile).generate("retry", "cv", base_cv=cv)
    assert result.standalone_project_names() == ["Transit Map", "Weather Archive"]


# --- rendering ----------------------------------------------------------------------

def rich_cv():
    return base_cv(
        standalone_projects=[obj("Transit Map", ["Mapped public transport gaps in 12 areas."]), "Weather Archive"],
    )


def test_every_new_field_reaches_upload_docx_and_txt(rich_profile, tmp_path):
    cv = rich_cv()
    check(cv, rich_profile)
    paths = render_upload_cv(cv, rich_profile, tmp_path)
    word = [p.text for p in Document(paths["cv_upload_docx_path"]).paragraphs]
    assert Path(paths["cv_upload_text_path"]).read_text(encoding="utf-8").splitlines() == word
    text = "\n".join(word)
    assert "Transit Map — University team project | 2024\nMapped public transport gaps in 12 areas." in text
    assert "Technologies: Python, Leaflet" in word
    assert "Weather Archive\nCatalogued public weather records." in text
    assert "Thesis: Synthetic Forecasting · Focus: causal inference" in word
    assert "Structured Certificate (Example Body, 2024)" in word and "Plain Certificate" in word
    assert "A. Sample (2024). Second Paper. Example Press.\nPeer-reviewed by two referees." in text
    assert "Volunteer mentor, Community Data Club.\nRan monthly SQL clinics." in text
    assert "A. Sample (2025). Transit & Access. Example Journal." in word  # verbatim citation


def test_employer_project_metadata_and_display_name(rich_profile, tmp_path):
    data = json.loads(rich_profile.model_dump_json())
    data["experience"][0]["selected_projects"][0].update(
        dates="2023", context="Internal rebuild", technologies=["dbt"])
    profile = Profile.model_validate(data)
    paths = render_upload_cv(base_cv(), profile, tmp_path)
    word = [p.text for p in Document(paths["cv_upload_docx_path"]).paragraphs]
    assert "Project: Attribution Rebuild (Northwind)" in word       # display_name, not the full company
    assert "— Internal rebuild | 2023" in word and "Technologies: dbt" in word
    assert "Northwind Analytics GmbH | April 2023 - Present | Sampletown, Germany" in word  # heading keeps it


def test_a_role_that_is_one_project_prints_an_italic_subheading(analyst_profile, tmp_path):
    data = json.loads(analyst_profile.model_dump_json())
    data["experience"][0]["bullets"] = []
    profile = Profile.model_validate(data)
    cv = base_cv()
    cv.experience[0].bullets = []
    renderer = LaTeXRenderer(outputs_dir=tmp_path)
    source = renderer.jinja_env.get_template("main.tex.jinja2").render(
        **renderer._prepare_template_data(cv, profile), layout=PRESETS[0],
        break_before_employer_index=None, split_before=None)
    assert r"\projectsubheading{Attribution Rebuild}" in source
    assert source.count(r"\projectheading{") == 0
    paths = render_upload_cv(cv, profile, tmp_path)
    document = Document(paths["cv_upload_docx_path"])
    heading = next(p for p in document.paragraphs if p.text == "Attribution Rebuild")
    assert heading.runs and all(run.italic for run in heading.runs)
    assert not any("Project: Attribution Rebuild" in p.text for p in document.paragraphs)
    # With regular bullets the labelled form stays.
    normal = renderer.jinja_env.get_template("main.tex.jinja2").render(
        **renderer._prepare_template_data(base_cv(), analyst_profile), layout=PRESETS[0],
        break_before_employer_index=None, split_before=None)
    assert r"\projectheading{Attribution Rebuild}{Northwind Analytics GmbH}" in normal
    assert "projectsubheading{" not in normal.split(r"\begin{document}")[1]


def test_review_expectations_cover_the_new_shapes(rich_profile):
    cv = rich_cv()
    snapshot = json.loads(rich_profile.model_dump_json())
    paragraphs, fields = _expected_cv_text({"cv": cv.model_dump(), "_profile_snapshot": snapshot})
    assert "Mapped public transport gaps in 12 areas." in paragraphs
    assert "Mapped 12 public transport gaps with open data." not in paragraphs  # the tailored text
    values = set(fields.values())
    assert {"Structured Certificate (Example Body, 2024)", "Plain Certificate",
            "Peer-reviewed by two referees.", "Ran monthly SQL clinics.",
            "Thesis: Synthetic Forecasting · Focus: causal inference",
            "University team project"} <= values


@pytest.mark.requires_latex
@pytest.mark.skipif(not latex_available(), reason="pdflatex unavailable")
def test_the_pdf_shows_every_new_field(rich_profile, tmp_path):
    cv = rich_cv()
    renderer = LaTeXRenderer(outputs_dir=tmp_path)
    pdf = renderer.render_cv(cv, rich_profile)
    reader = PdfReader(pdf)
    text = " ".join(" ".join(page.extract_text() or "" for page in reader.pages).split())
    for needle in ("Transit Map — University team project | 2024", "Technologies: Python, Leaflet",
                   "Mapped public transport gaps in 12 areas.", "Weather Archive",
                   "Thesis: Synthetic Forecasting · Focus: causal inference",
                   "Structured Certificate (Example Body, 2024)",
                   "Peer-reviewed by two referees.", "Ran monthly SQL clinics.",
                   "Example Press."):
        assert needle in text, needle
    assert "Selected Projects: Attribution Rebuild (Northwind)" in text
    assert len(reader.pages) <= 2
    assert renderer.last_layout["text_preserved"]
