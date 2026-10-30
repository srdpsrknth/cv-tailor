"""The reading packet and the verdict gate (Q7).

The owner reserved writing, PDF and layout quality for themselves, and ``evaluation``
measures none of the three. So the run cannot end at a table: it ends at documents a
person reads, plus a place to record what they thought, plus a code path that refuses to
promote anything until that record exists.

These tests pin the properties that make that a mechanism rather than a promise:

* the packet holds the **rendered** documents, per model per case, in the study's order;
* attribution is by the run's **own manifest**, so one model's documents are never
  handed to another -- the bug the first implementation had, found by running it against
  the real store;
* a candidate with nothing to read is **inconclusive, not failed**;
* an untouched verdict file promotes nothing, and prose promotes exactly its own model.

Everything here is offline, and it reads only a synthetic sandbox tree it builds itself.
"""
from __future__ import annotations

import json

import pytest

try:
    from evaluation import reading_packet
    from evaluation.reading_packet import (
        VERDICTS_FILENAME,
        ReadingPacket,
        build_packet,
        load_verdicts,
        parity_with_verdicts,
    )
except ImportError as error:  # pragma: no cover - only on a broken tree
    pytest.fail(
        f"evaluation.reading_packet could not be imported: {error}", pytrace=False
    )


# --- a synthetic run tree ------------------------------------------------------------------

def _job(profile_dir, job_id, model_id, *, documents=("cv.pdf", "letter.pdf", "letter.docx"),
         manifest=True):
    """One job folder as ``tailor_documents`` leaves it."""
    folder = profile_dir / job_id
    source = folder / "source"
    source.mkdir(parents=True, exist_ok=True)
    for name in documents:
        (folder / name).write_bytes(b"%PDF-1.4 synthetic")
    (source / "content.json").write_text("{}", encoding="utf-8")
    if manifest:
        (source / "generation_result.json").write_text(
            json.dumps({"models": {"cv": model_id, "cover_letter": model_id}}),
            encoding="utf-8",
        )
    return folder


def _run_tree(root, spec):
    """``spec`` maps case name -> list of (job_id, model_id)."""
    outputs = root / "outputs"
    for case_name, jobs in spec.items():
        profile = outputs / f"eval_{case_name}"
        profile.mkdir(parents=True, exist_ok=True)
        for job_id, model_id in jobs:
            _job(profile, job_id, model_id)
    return outputs


# --- the packet collects rendered documents -------------------------------------------------

def test_the_packet_holds_the_rendered_documents(tmp_path):
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/one")]})
    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/one",))

    assert packet.document_count == 3
    (case,) = packet.cases
    names = sorted(p.name for p in case.documents)
    assert names == ["cv.pdf", "letter.docx", "letter.pdf"]


def test_pdfs_are_listed_before_the_docx(tmp_path):
    """A reader wants the rendered page first and the editable artefact second.

    The two layouts differ -- AGENTS.md requires checking both -- so the order is stated
    rather than left to directory iteration.
    """
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/one")]})
    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/one",))

    (case,) = packet.cases
    suffixes = [p.suffix for p in case.documents]
    assert suffixes.index(".pdf") < suffixes.index(".docx")


def test_the_editable_source_is_kept_beside_the_documents(tmp_path):
    """So a reading can be traced to the bytes behind it."""
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/one")]})
    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/one",))

    (case,) = packet.cases
    assert case.source, "the packet dropped the source, so a reading is untraceable"
    assert any(p.name == "content.json" for p in case.source)
    # In a subdirectory, not mixed in with the documents a reader is looking at.
    assert all("source" in p.parts for p in case.source)


def test_the_folder_name_carries_the_rank_model_and_case(tmp_path):
    """The shape the 2026-10-26 packet used, kept so a reader recognises it."""
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "openai/gpt-6-luna")]})
    packet = build_packet(outputs, tmp_path / "packet", ranking=("openai/gpt-6-luna",))

    (case,) = packet.cases
    assert case.folder_name == "1-openai_gpt-6-luna-eval_nordwind"


def test_the_rank_reflects_the_ranking_given(tmp_path):
    """Numbered by the study's order, so a reader sees it before forming their own."""
    outputs = _run_tree(tmp_path, {
        "nordwind": [("2026_a_100", "vendor/one"), ("2026_a_101", "vendor/two")],
    })
    packet = build_packet(
        outputs, tmp_path / "packet", ranking=("vendor/two", "vendor/one")
    )

    by_model = {c.model_id: c.rank for c in packet.cases}
    assert by_model["vendor/two"] == 1
    assert by_model["vendor/one"] == 2


# --- attribution, which is where the first implementation was wrong ------------------------

def test_a_model_gets_only_its_own_documents(tmp_path):
    """**The bug the first implementation had, found by running it against the real store.**

    A sandbox store accumulates every job folder from every past run. Selecting the newest
    folder per case attributed whichever run happened to be last to *every* model in the
    ranking, so a model that never ran was handed three folders of another model's work.
    Attribution is now read from each folder's own manifest.
    """
    outputs = _run_tree(tmp_path, {
        "nordwind": [
            ("2026_a_100", "vendor/old-run"),
            ("2026_a_101", "vendor/current"),
        ],
    })
    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/current",))

    (case,) = packet.cases
    assert len(packet.cases) == 1
    # The document set came from the folder that names this model, not the newest one.
    manifest = next(p for p in case.source if p.name == "generation_result.json")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["models"]["cv"] == "vendor/current"


def test_a_model_that_never_ran_gets_no_folder_and_is_reported(tmp_path):
    """``mistral-small-2603`` produced nothing because every call was rate-limited.

    The owner called that **inconclusive rather than failed**, and the packet must keep
    that distinction: asking for a quality verdict about a model that produced nothing
    would invite a verdict about the absence of evidence.
    """
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/ran")]})
    packet = build_packet(
        outputs, tmp_path / "packet", ranking=("vendor/ran", "vendor/never-ran")
    )

    assert [c.model_id for c in packet.cases] == ["vendor/ran"]
    assert [m for m, _ in packet.missing] == ["vendor/never-ran"]
    assert "INCONCLUSIVE, not failed" in packet.describe()
    assert not (tmp_path / "packet" / "2-vendor_never-ran-eval_nordwind").exists()


def test_an_unattributable_folder_is_not_handed_to_a_model(tmp_path):
    """No manifest means "cannot attribute", never "assume it was this one"."""
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/x")]})
    # Strip the manifest, as a truncated or older run would have.
    (outputs / "eval_nordwind" / "2026_a_100" / "source" / "generation_result.json").unlink()

    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/x",))
    assert packet.cases == ()
    assert [m for m, _ in packet.missing] == ["vendor/x"]


def test_a_rerun_of_one_model_prefers_the_newest_folder(tmp_path):
    """Recency breaks ties *within* one model's own folders, and only there."""
    outputs = _run_tree(tmp_path, {
        "nordwind": [
            ("2026_a_100", "vendor/x"),
            ("2026_a_999", "vendor/x"),
        ],
    })
    (outputs / "eval_nordwind" / "2026_a_999" / "cv.pdf").write_bytes(b"newest")

    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/x",))
    (case,) = packet.cases
    cv = next(p for p in case.documents if p.name == "cv.pdf")
    assert cv.read_bytes() == b"newest"


def test_a_folder_with_no_documents_is_skipped(tmp_path):
    """A failed run leaves a folder with a manifest and no rendered pages."""
    outputs = tmp_path / "outputs"
    profile = outputs / "eval_nordwind"
    profile.mkdir(parents=True)
    _job(profile, "2026_a_100", "vendor/x", documents=())
    _job(profile, "2026_a_101", "vendor/x")

    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/x",))

    assert len(packet.cases) == 1, "the empty folder was offered as something to read"


def test_cases_can_be_restricted(tmp_path):
    outputs = _run_tree(tmp_path, {
        "nordwind": [("2026_a_100", "vendor/x")],
        "lumen": [("2026_a_101", "vendor/x")],
    })
    packet = build_packet(
        outputs, tmp_path / "packet", ranking=("vendor/x",), cases=("nordwind",)
    )

    assert [c.case_name for c in packet.cases] == ["nordwind"]


def test_a_rerun_does_not_leave_a_stale_folder(tmp_path):
    """A stale folder is worse than a missing one: it shows a model no longer a candidate."""
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/old")]})
    destination = tmp_path / "packet"
    build_packet(outputs, destination, ranking=("vendor/old",))
    assert (destination / "1-vendor_old-eval_nordwind").exists()

    outputs2 = _run_tree(tmp_path / "second", {"nordwind": [("2026_a_200", "vendor/new")]})
    build_packet(outputs2, destination, ranking=("vendor/new",))

    names = sorted(p.name for p in destination.iterdir() if p.is_dir())
    assert names == ["1-vendor_new-eval_nordwind"]


# --- the verdict file ----------------------------------------------------------------------

def test_the_verdict_file_is_written_with_a_section_per_model(tmp_path):
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/one")]})
    packet = build_packet(
        outputs, tmp_path / "packet", ranking=("vendor/one", "vendor/two")
    )

    text = packet.verdicts_path.read_text(encoding="utf-8")
    assert packet.verdicts_path.name == VERDICTS_FILENAME
    # Both models get a section, including the one with nothing to read, so the absence is
    # visible in the file a person is working in rather than only in the console.
    assert "## vendor/one" in text
    assert "## vendor/two" in text
    assert "Models with nothing to read" in text


def test_the_verdict_file_asks_the_four_questions_the_owner_established(tmp_path):
    """From the 2026-10-26 packet's own HOW-TO-REPORT.md, so the format is not reinvented."""
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/one")]})
    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/one",))
    text = packet.verdicts_path.read_text(encoding="utf-8")

    assert "would send?" in text
    assert "this* posting" in text or "this posting" in text
    assert "PDF problems" in text
    assert "factual problems" in text


def test_the_verdict_file_says_a_disagreeing_ranking_is_the_finding(tmp_path):
    """The folder numbers carry the study's order; disagreement with it is the point."""
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/one")]})
    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/one",))
    text = packet.verdicts_path.read_text(encoding="utf-8")

    assert "disagrees with that" in text
    assert "changes the recommendation" in text


def test_the_verdict_file_says_verdicts_are_required_for_eligibility(tmp_path):
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/one")]})
    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/one",))
    text = packet.verdicts_path.read_text(encoding="utf-8")

    assert "not eligible for curation" in text
    assert "enforced in code" in text


def test_run_notes_are_carried_into_the_verdict_file(tmp_path):
    """A note explaining the numbers belongs in front of the reader, not lost in a log."""
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/one")]})
    packet = build_packet(
        outputs, tmp_path / "packet", ranking=("vendor/one",),
        notes=("glm-5.3-flash emptied its response at the 8,000 ceiling.",),
    )
    text = packet.verdicts_path.read_text(encoding="utf-8")

    assert "glm-5.3-flash emptied its response" in text


# --- reading verdicts back -----------------------------------------------------------------

def test_an_untouched_verdict_file_yields_no_verdicts(tmp_path):
    """**The property that stops a placeholder promoting a candidate.**

    The file is written with the questions already in it, so "the file exists" must not
    read as "the owner answered".
    """
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/one")]})
    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/one",))

    verdicts = load_verdicts(packet.verdicts_path)
    assert verdicts["vendor/one"] == ""
    assert parity_with_verdicts(packet, verdicts)["without_verdict"] == ("vendor/one",)


def test_prose_under_a_heading_is_read_back(tmp_path):
    """Free-form, in the owner's own words -- the format they asked for."""
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/one")]})
    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/one",))

    text = packet.verdicts_path.read_text(encoding="utf-8")
    text = text.replace(
        "## vendor/one\n",
        "## vendor/one\n\nwould send: yes. Specific to the posting, no orphan headings.\n",
    )
    packet.verdicts_path.write_text(text, encoding="utf-8")

    verdicts = load_verdicts(packet.verdicts_path)
    assert "would send: yes" in verdicts["vendor/one"]
    assert parity_with_verdicts(packet, verdicts)["with_verdict"] == ("vendor/one",)


def test_the_prompt_lines_alone_are_not_a_verdict(tmp_path):
    """A reader who deletes nothing but writes nothing has not answered."""
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/one")]})
    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/one",))

    text = packet.verdicts_path.read_text(encoding="utf-8")
    # Answer one question only; the other prompt lines remain untouched.
    text = text.replace(
        "## vendor/one\n",
        "## vendor/one\n\n- would send? (yes / no / only after edits): yes\n",
    )
    packet.verdicts_path.write_text(text, encoding="utf-8")

    # The prompt lines are stripped, so what remains is the answer without its label.
    verdicts = load_verdicts(packet.verdicts_path)
    assert "yes" in verdicts["vendor/one"]
    assert "would send?" not in verdicts["vendor/one"]


def test_a_blank_body_between_sections_is_no_verdict(tmp_path):
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/one")]})
    packet = build_packet(
        outputs, tmp_path / "packet", ranking=("vendor/one", "vendor/two")
    )
    text = packet.verdicts_path.read_text(encoding="utf-8")
    text = text.replace("## vendor/two\n", "## vendor/two\n\n   \n\n")
    packet.verdicts_path.write_text(text, encoding="utf-8")

    verdicts = load_verdicts(packet.verdicts_path)
    assert verdicts["vendor/two"] == ""


def test_parity_distinguishes_unreadable_from_unjudged(tmp_path):
    """Asking for a quality verdict about a model that produced nothing invites a verdict
    about the absence of evidence."""
    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/ran")]})
    packet = build_packet(
        outputs, tmp_path / "packet", ranking=("vendor/ran", "vendor/never-ran")
    )
    parity = parity_with_verdicts(packet, {})

    assert "vendor/ran" in parity["without_verdict"]
    # `never-ran` is not "missing a verdict" -- it produced nothing to judge.
    assert parity["unreadable"] == ()


def test_load_verdicts_on_a_missing_file_is_an_error_not_a_silent_blank(tmp_path):
    """A missing verdict file must not read as "no verdicts".

    Those two states are not the same thing: one is a mistake in a path, the other is a
    file that exists and has not been filled in. Reporting both as "empty" would hide the
    first behind the second.
    """
    with pytest.raises(FileNotFoundError):
        load_verdicts(tmp_path / "absent.md")


# --- the packet describes itself usefully --------------------------------------------------

def test_describe_counts_models_cases_and_documents(tmp_path):
    outputs = _run_tree(tmp_path, {
        "nordwind": [("2026_a_100", "vendor/one")],
        "lumen": [("2026_a_101", "vendor/one")],
    })
    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/one",))
    text = packet.describe()

    assert "1 model(s)" in text
    assert "2 case folder(s)" in text
    assert "6 document(s)" in text


def test_models_are_listed_in_rank_order(tmp_path):
    outputs = _run_tree(tmp_path, {
        "nordwind": [("2026_a_100", "vendor/one"), ("2026_a_101", "vendor/two")],
    })
    packet = build_packet(
        outputs, tmp_path / "packet", ranking=("vendor/two", "vendor/one")
    )

    assert packet.models() == ("vendor/two", "vendor/one")


def test_an_empty_output_tree_produces_a_packet_that_says_so(tmp_path):
    """No documents is a reportable state, not a crash."""
    empty = tmp_path / "outputs"
    empty.mkdir()
    packet = build_packet(empty, tmp_path / "packet", ranking=("vendor/one",))

    assert packet.cases == ()
    assert packet.document_count == 0
    assert "No documents to read" in packet.describe()


def test_the_packet_reads_only_the_tree_it_was_given(tmp_path):
    """The private store is never read: the suite writes synthetic fixtures only.

    Asserted by building a packet while the store path a real run would use is absent --
    if this module reached for it, the call would be visible here.
    """
    from pathlib import Path

    outputs = _run_tree(tmp_path, {"nordwind": [("2026_a_100", "vendor/one")]})
    packet = build_packet(outputs, tmp_path / "packet", ranking=("vendor/one",))

    real_store = Path.home() / "nonexistent-store"
    assert not real_store.exists()
    for case in packet.cases:
        for path in case.documents + case.source:
            assert str(tmp_path) in str(path)
