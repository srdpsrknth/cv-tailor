"""Geometry and selection checks using small synthetic, real PDF text streams."""

import json

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    DecodedStreamObject, DictionaryObject, NameObject,
)

from renderers.cv_layout import (
    PRESETS,
    measure_layout,
    preview_breaks,
    preview_quality_score,
    rank_layout,
    read_layout_metadata,
)


def _pdf(tmp_path, pages):
    writer = PdfWriter()
    width, height = 595.28, 841.89
    for lines in pages:
        page = writer.add_blank_page(width=width, height=height)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
        })
        stream = DecodedStreamObject()
        commands = []
        for x, top, text in lines:
            safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"BT /F1 10 Tf 1 0 0 1 {x} {height-top-8} Tm ({safe}) Tj ET")
        stream.set_data("\n".join(commands).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    path = tmp_path / "synthetic.pdf"
    writer.write(path)
    return path


def _report(fractions, *, split=0, gap=12, clipping=False, orphan=False):
    pages = [{"used_height_fraction": value, "largest_gap_pt": gap}
             for value in fractions]
    # Tests compare intended preferences independently of the metric formula.
    score = (sum(max(0, .75-v) * 100 + max(0, v-.95) * 100
                 for v in fractions) + abs(fractions[0]-fractions[-1]) * 20
             + split * 3)
    return dict(page_count=len(pages), pages=pages, clipping=clipping,
                orphan_headings=orphan, employer_project_splits=split,
                quality_score=score)


def test_presets_keep_readable_body_and_metadata_contract():
    assert [p["name"] for p in PRESETS] == ["comfortable", "standard", "compact"]
    assert all(p["body_size"] >= 10.5 and p["leading"] > p["body_size"]
               for p in PRESETS)


def test_measurements_use_printable_bounds_and_do_not_store_text(tmp_path):
    path = _pdf(tmp_path, [[(45, 43, "Private example"), (45, 570, "Final line")]])
    report = measure_layout(path)
    page = report["pages"][0]
    assert report["page_count"] == 1
    assert page["used_height_fraction"] == pytest.approx(.71, abs=.005)
    # Excludes the intended 15mm bottom margin.
    assert page["blank_tail_mm"] == pytest.approx(77.4, abs=1)
    assert page["largest_gap_pt"] > 500
    assert "Private" not in json.dumps(report)
    assert not report["clipping"]


def test_role_project_split_ignores_parenthetical_employer_repeat(tmp_path):
    path = _pdf(tmp_path, [
        [(45, 43, "Example Ltd"), (45, 60, "Analyst"), (45, 100, "Role evidence")],
        [(45, 43, "Selected Projects: Example Project (Example Ltd)"),
         (45, 60, "Project evidence")],
    ])
    report = measure_layout(path, employer_names=["Example Ltd"],
                            project_names=[("Example Ltd", "Example Project")])
    assert report["employer_project_splits"] == 1
    assert report["split_employer_indices"] == [0]
    assert not report["orphan_headings"]


def test_project_on_same_page_is_not_a_split(tmp_path):
    path = _pdf(tmp_path, [[(45, 43, "Example Ltd"),
                           (45, 80, "Selected Projects: Example Project (Example Ltd)"),
                           (45, 100, "Project evidence")]])
    report = measure_layout(path, employer_names=["Example Ltd"],
                            project_names=[("Example Ltd", "Example Project")])
    assert report["employer_project_splits"] == 0
    assert report["split_employer_indices"] == []


def test_preview_targets_the_first_whole_role_on_page_two(tmp_path):
    path = _pdf(tmp_path, [
        [(45, 43, "First Company"), (45, 650, "First role evidence")],
        [(45, 43, "Next Company"), (45, 60, "New role evidence"),
         (45, 730, "Last line")],
    ])
    report = measure_layout(path, employer_names=["First Company", "Next Company"])
    assert list(preview_breaks(report, [(3, 2), (4, 2)])) == [
        (1, "bullet", 1), (1, "project", 0),
    ]


def test_preview_can_try_the_second_project_in_a_continuation(tmp_path):
    path = _pdf(tmp_path, [
        [(45, 43, "First Company"), (45, 635, "Role evidence")],
        [(45, 43, "Selected Projects: Warehouse migration"),
         (45, 730, "Project evidence")],
    ])
    report = measure_layout(path, employer_names=["First Company"],
                            project_names=[("First Company", "Warehouse migration")])
    assert list(preview_breaks(report, [(2, 3)])) == [
        (0, "bullet", 1), (0, "project", 1),
    ]


def test_preview_avoids_ambiguous_and_short_roles(tmp_path):
    path = _pdf(tmp_path, [
        [(45, 43, "Repeat Company"), (45, 640, "First role evidence")],
        [(45, 43, "Repeat Company"), (45, 60, "Next role evidence")],
    ])
    report = measure_layout(path, employer_names=["Repeat Company", "Repeat Company"])
    assert list(preview_breaks(report, [(1, 0), (4, 3)])) == []
    assert list(preview_breaks({**report, "page_count": 1}, [(1, 0)])) == []


def test_preview_prefers_a_shorter_maximum_tail_but_charges_for_continuation():
    long_tail = {"quality_score": 2, "pages": [
        {"blank_tail_mm": 50}, {"blank_tail_mm": 22},
    ]}
    short_tails = {"quality_score": 2, "pages": [
        {"blank_tail_mm": 32}, {"blank_tail_mm": 37},
    ]}
    assert preview_quality_score(short_tails, continued=True) < preview_quality_score(long_tail)
    assert preview_quality_score(short_tails) < preview_quality_score(short_tails, continued=True)


@pytest.mark.parametrize("heading", ["EDUCATION", "Example Ltd",
                                     "Selected Projects: Example Project"])
def test_stranded_heading_is_detected(tmp_path, heading):
    path = _pdf(tmp_path, [[(45, 43, "Body"), (45, 760, heading)]])
    assert measure_layout(path, employer_names=["Example Ltd"])["orphan_headings"]


def test_clipping_is_detected_from_glyphs_not_text_extraction(tmp_path):
    path = _pdf(tmp_path, [[(-5, 43, "Outside the page")]])
    assert measure_layout(path)["clipping"]


def test_missing_unreadable_or_text_free_pdf_cannot_pass(tmp_path):
    with pytest.raises(FileNotFoundError):
        measure_layout(tmp_path / "missing.pdf")
    path = tmp_path / "bad.pdf"
    path.write_text("not a PDF")
    with pytest.raises(Exception):
        measure_layout(path)
    with pytest.raises(ValueError, match="extractable text"):
        measure_layout(_pdf(tmp_path, [[]]))


def test_safe_two_pages_beats_overflow_and_defects():
    safe = _report([.93, .70])
    assert rank_layout(safe, 2) < rank_layout(_report([.90, .90, .10]))
    assert rank_layout(safe, 2) < rank_layout(_report([.88, .88], clipping=True))
    assert rank_layout(safe, 2) < rank_layout(_report([.88, .88], orphan=True))


def test_balanced_pages_beat_crowded_first_and_sparse_second():
    assert rank_layout(_report([.87, .88]), 1) < rank_layout(_report([.98, .70]), 0)


def test_real_one_page_fit_wins_over_unnecessary_second_page():
    assert rank_layout(_report([.90]), 2) < rank_layout(_report([.85, .50]), 0)


def test_overflow_ranking_preserves_smallest_count_for_shortening_retry():
    assert rank_layout(_report([.99, .99, .10]), 2) < rank_layout(_report([.90]*4), 0)


def test_clean_overflow_beats_clipped_or_stranded_two_pages():
    clean = _report([.90, .90, .10])
    assert rank_layout(clean, 2) < rank_layout(_report([.88, .88], clipping=True))
    assert rank_layout(clean, 2) < rank_layout(_report([.88, .88], orphan=True))


def test_readability_is_stable_tiebreaker_without_overriding_large_balance_gain():
    report = _report([.88, .88])
    assert rank_layout(report, 0) < rank_layout(report, 1) < rank_layout(report, 2)
    assert rank_layout(report, 2) < rank_layout(_report([.98, .70]), 0)


def _with_metadata(path, data):
    writer = PdfWriter(clone_from=PdfReader(path))
    writer.add_metadata({"/CVLayout": json.dumps(data)})
    with path.open("wb") as stream:
        writer.write(stream)


def test_layout_metadata_roundtrip_and_legacy_unknown(tmp_path):
    path = _pdf(tmp_path, [[(45, 43, "Body")]])
    assert read_layout_metadata(path) is None
    data = {**measure_layout(path), "preset": "comfortable"}
    _with_metadata(path, data)
    assert read_layout_metadata(path) == data
    data["preset"] = "custom"
    _with_metadata(path, data)
    assert read_layout_metadata(path)["preset"] == "custom"


@pytest.mark.parametrize("change", [
    {"schema_version": 2}, {"schema_version": True}, {"preset": "tiny"},
    {"page_count": "1"}, {"page_count": True}, {"page_count": 2},
    {"pages": {}}, {"pages": []}, {"pages": [None]},
    {"pages": [{"page": "1"}]},
    {"pages": [{"page": 1, "used_height_fraction": float("nan"),
                "blank_tail_mm": 1, "largest_gap_pt": 1}]},
    {"warnings": None}, {"warnings": 1}, {"warnings": "warning"},
    {"warnings": [None]}, {"warnings": [{"private": "input"}]},
    {"body_size": True}, {"body_size": 0}, {"body_size": float("inf")},
    {"leading": -1}, {"leading": "13.2"},
])
def test_malformed_layout_metadata_remains_unknown(tmp_path, change):
    path = _pdf(tmp_path, [[(45, 43, "Body")]])
    data = {**measure_layout(path), "preset": "comfortable", **change}
    _with_metadata(path, data)
    assert read_layout_metadata(path) is None


def test_metadata_reader_handles_missing_invalid_json_and_unreadable_files(tmp_path):
    assert read_layout_metadata(tmp_path / "missing.pdf") is None
    bad = tmp_path / "bad.pdf"
    bad.write_text("private parser input")
    assert read_layout_metadata(bad) is None
    path = _pdf(tmp_path, [[(45, 43, "Body")]])
    writer = PdfWriter(clone_from=PdfReader(path))
    writer.add_metadata({"/CVLayout": "not JSON"})
    with path.open("wb") as stream:
        writer.write(stream)
    assert read_layout_metadata(path) is None


def test_metadata_reader_rejects_oversize_payload_and_accepts_optional_fields(tmp_path):
    path = _pdf(tmp_path, [[(45, 43, "Body")]])
    data = {**measure_layout(path), "preset": "comfortable", "body_size": 11, "leading": 13.2}
    data.pop("warnings")
    _with_metadata(path, data)
    assert read_layout_metadata(path) == data
    data["warnings"] = ["x" * 1_000_001]
    _with_metadata(path, data)
    assert read_layout_metadata(path) is None
