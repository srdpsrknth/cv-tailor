"""The reading packet: the artefacts a person needs to judge what the suite cannot.

**Why this is part of the workflow and not a convenience.** ``evaluation`` measures
whether a document was accepted by the factual gate, what it cost and how many correction
calls it took. It measures **no prose and no rendering** -- ``cv_page_count`` is the only
thing it records about a rendered document, and there is no orphan-heading, clipping,
whitespace or typography measurement anywhere in it (ADR 0014). ADR 0016 records the
consequence directly: the person tuning a candidate's inputs is not the person judging its
output, and only a human reading the documents can tell "this model writes well" from
"this model was asked well".

So the run cannot end at a table. It ends at a folder of documents a person reads, plus a
place to write down what they thought -- and :mod:`evaluation.curation_diff` refuses to
promote any entry to eligible until that verdict exists.

**The shape is not invented here.** The 2026-10-26 study produced exactly this by hand:
``<rank>-<model>-<case>/`` folders holding the CV PDF, the cover-letter PDF and the
cover-letter DOCX, with a README explaining how to report. This module builds that same
packet, so the next re-curation does not rebuild it in a session -- and a test asserts the
layout matches, so the two cannot drift.

**Reading order is deliberate.** Folders are numbered by the study's own ranking, so the
folder named ``1-`` is the study's cheapest-per-accepted-result candidate. When a reading
disagrees with that order, the disagreement *is* the finding -- which is why the number is
in the folder name rather than only in a table.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

#: The documents a candidate's job folder holds, in the order a reader wants them: the CV,
#: then the letter as PDF (what a reader sees), then as DOCX (the editable artefact, which
#: is what reveals real font size and spacing -- the two differ from the LaTeX PDF and
#: AGENTS.md requires checking both).
PACKET_DOCUMENT_SUFFIXES = (".pdf", ".docx")

#: The file a person fills in. Deliberately a plain text file with the questions already
#: written into it, because the 2026-10-26 session's most useful correction was that a
#: rubric is not wanted -- "a line or two per model, in your own words".
VERDICTS_FILENAME = "VERDICTS.md"

#: The prompts the verdict file writes, **in full**. Matching on the whole question rather
#: than a prefix is what lets an answered line be told from an untouched one: the template
#: line is "- would send? (yes / no / only after edits):", and a prefix match on
#: "- would send?" leaves "(yes / no / only after edits):" looking like an answer -- which
#: it did, and an untouched file came back as four lines of template text.
_PROMPT_LINES = (
    "- would send? (yes / no / only after edits):",
    "- reads specific to *this* posting, or generic?:",
    "- PDF problems (clipping, orphan headings, spacing, type size, awkward page break):",
    "- factual problems (unsupported claim, wrong date, changed employer wording):",
)

#: One line per model, matching the free-form template the owner already used.
_PROMPT_TEMPLATE = """\
## {model_id}

- would send? (yes / no / only after edits):
- reads specific to *this* posting, or generic?:
- PDF problems (clipping, orphan headings, spacing, type size, awkward page break):
- factual problems (unsupported claim, wrong date, changed employer wording):

"""


@dataclass(frozen=True)
class PacketCase:
    """One accepted run: the documents for one candidate against one case."""

    model_id: str
    case_name: str
    #: The study's own rank by cost per accepted result, 1-based. In the folder name so a
    #: reader sees the study's order before forming their own.
    rank: int
    directory: Path
    documents: tuple[Path, ...] = ()
    source: tuple[Path, ...] = ()

    @property
    def folder_name(self) -> str:
        return self.directory.name

    def describe(self) -> str:
        return (
            f"{self.rank}. {self.model_id} x {self.case_name}: "
            f"{len(self.documents)} document(s)"
        )


@dataclass
class ReadingPacket:
    """A folder of documents to read, plus the file to record verdicts in.

    :attr:`missing` is first-class rather than a log line. A candidate with no documents
    is not a candidate that failed -- ``mistral-small-2603`` produced nothing at all
    because every call was rate-limited upstream, which the owner correctly called
    **inconclusive rather than failed**. Reporting it as absent, with the reason, is what
    keeps that distinction.
    """

    root: Path
    cases: tuple[PacketCase, ...] = ()
    missing: tuple[tuple[str, str], ...] = ()
    verdicts_path: Optional[Path] = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def document_count(self) -> int:
        return sum(len(case.documents) for case in self.cases)

    def models(self) -> tuple[str, ...]:
        seen, ordered = set(), []
        for case in sorted(self.cases, key=lambda c: c.rank):
            if case.model_id not in seen:
                seen.add(case.model_id)
                ordered.append(case.model_id)
        return tuple(ordered)

    def describe(self) -> str:
        lines = [
            f"Reading packet: {self.root}",
            f"  {len(self.models())} model(s), {len(self.cases)} case folder(s), "
            f"{self.document_count} document(s)",
            "",
        ]
        for case in sorted(self.cases, key=lambda c: (c.rank, c.case_name)):
            lines.append(f"  {case.describe()}")
        if self.missing:
            lines.append("")
            lines.append("No documents to read:")
            for model_id, reason in self.missing:
                lines.append(f"  - {model_id}: {reason}")
            lines.append(
                "    A candidate with nothing to read is INCONCLUSIVE, not failed, when "
                "the cause was upstream (a rate limit, a timeout). Do not record a "
                "quality verdict about a model that produced nothing."
            )
        if self.verdicts_path is not None:
            lines.append("")
            lines.append(f"Record your verdicts in: {self.verdicts_path}")
            lines.append(
                "  Until a verdict exists, the model is not eligible for curation -- "
                "this suite does not measure writing, PDF or layout quality."
            )
        return "\n".join(lines)


def _documents_in(job_folder: Path) -> tuple[Path, ...]:
    """The reader-facing documents in a job folder, at its top level.

    Top level only, deliberately: ``source/`` holds ``content.json``, the drafts and the
    manifest, which are the editable and audit artefacts. A reader wants the rendered
    pages; the source belongs beside them rather than in front of them.
    """
    if not job_folder.is_dir():
        return ()
    return tuple(
        sorted(
            (p for p in job_folder.iterdir()
             if p.is_file() and p.suffix.lower() in PACKET_DOCUMENT_SUFFIXES),
            key=lambda p: (p.suffix.lower() != ".pdf", p.name),
        )
    )


def _source_in(job_folder: Path) -> tuple[Path, ...]:
    """The editable and audit artefacts, kept so a reading can be traced to its bytes."""
    source = job_folder / "source"
    if not source.is_dir():
        return ()
    return tuple(sorted(p for p in source.iterdir() if p.is_file()))


def _safe_model_slug(model_id: str) -> str:
    """``openai/gpt-6-luna`` -> ``openai_gpt-6-luna``.

    The 2026-10-26 packet used this spelling (``1-openai_gpt-6-luna-eval_analyst_lumen``),
    so it is kept rather than reinvented -- a reader who has used the packet before should
    recognise it.
    """
    return model_id.replace("/", "_")


def _model_from_manifest(job_folder: Path) -> Optional[str]:
    """The model that produced this job folder, read from its own manifest.

    ``generation_result.json`` records ``models`` as a per-task mapping (``cv``,
    ``cover_letter``, ``layout_retry``). The CV's model is taken, because a packet folder
    is one candidate's documents and the CV is the document the case exists for.

    Returns ``None`` when the manifest is absent or silent, which the caller treats as
    "unattributable" rather than assuming a model. Guessing here would silently attribute
    one model's documents to another -- the failure this function exists to prevent.
    """
    manifest = job_folder / "source" / "generation_result.json"
    if not manifest.is_file():
        return None
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    models = payload.get("models") or {}
    if not isinstance(models, dict):
        return None
    return models.get("cv") or models.get("cover_letter")


def build_packet(
    store_outputs: Path,
    destination: Path,
    *,
    ranking: tuple[str, ...],
    cases: tuple[str, ...] = (),
    clean: bool = True,
    notes: tuple[str, ...] = (),
) -> ReadingPacket:
    """Collect a reading packet from a finished run's output tree.

    Args:
        store_outputs: the run's ``outputs`` directory -- for a live evaluation run, the
            sandbox store's, ``.tmp/evaluation-store/outputs``. The private store is never
            read: the suite writes only synthetic fixtures into its own sandbox.
        destination: where the packet is written.
        ranking: model ids **best first**, by cost per accepted result. The index becomes
            the folder prefix, so the study's order is visible before a reader forms
            their own.
        cases: restrict to these case names; empty means every case found.
        clean: remove an existing packet first, so a re-run cannot leave a stale folder
            from a previous slate. A stale folder in a reading packet is worse than a
            missing one: it shows a model that is no longer a candidate.
        notes: anything about the run worth putting in front of the reader.

    **Attribution is by the run's own manifest, never by recency.** A sandbox store
    accumulates every job folder from every past run -- the 2026-10-30 store held six per
    case, one per model from six different runs -- so selecting the newest folder per case
    attributes whichever run happened to be last to *every* model in the ranking. That was
    the first implementation, and running it against the real store showed a model that
    never ran being handed three folders of another model's documents. Each folder is now
    matched to the model its own ``generation_result.json`` names.
    """
    store_outputs = Path(store_outputs)
    destination = Path(destination)

    if clean and destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    # The evaluation writes each case under a synthetic profile id (``eval_<case>``), so
    # the profile directory is the case. Read, never assumed.
    profile_dirs = sorted(p for p in store_outputs.iterdir() if p.is_dir()) \
        if store_outputs.is_dir() else []

    found: list[PacketCase] = []
    missing: list[tuple[str, str]] = []

    for rank, model_id in enumerate(ranking, start=1):
        slug = _safe_model_slug(model_id)
        model_seen = False
        for profile_dir in profile_dirs:
            case_name = profile_dir.name.removeprefix("eval_")
            if cases and case_name not in cases:
                continue
            # Newest first, then the first folder this model actually produced. Recency
            # only breaks ties *within* one model's own folders -- a re-run of the same
            # candidate -- which is the one case where the newest is the right answer.
            job_folder = next(
                (
                    p for p in sorted(profile_dir.iterdir(), reverse=True)
                    if p.is_dir()
                    and _documents_in(p)
                    and _model_from_manifest(p) == model_id
                ),
                None,
            )
            if job_folder is None:
                continue
            documents = _documents_in(job_folder)
            model_seen = True
            folder = destination / f"{rank}-{slug}-{profile_dir.name}"
            folder.mkdir(parents=True, exist_ok=True)
            copied = []
            for document in documents:
                target = folder / document.name
                shutil.copy2(document, target)
                copied.append(target)
            for item in _source_in(job_folder):
                source_dir = folder / "source"
                source_dir.mkdir(exist_ok=True)
                target = source_dir / item.name
                shutil.copy2(item, target)
            found.append(
                PacketCase(
                    model_id=model_id,
                    case_name=case_name,
                    rank=rank,
                    directory=folder,
                    documents=tuple(copied),
                    source=_source_in(folder),
                )
            )
        if not model_seen:
            missing.append(
                (
                    model_id,
                    "no rendered documents in the run's output tree -- either every "
                    "case failed the gate, or nothing was produced (a rate limit or an "
                    "empty response). Inconclusive, not failed, when upstream.",
                )
            )

    verdicts = destination / VERDICTS_FILENAME
    verdicts.write_text(_verdicts_text(ranking, missing, notes), encoding="utf-8")

    return ReadingPacket(
        root=destination,
        cases=tuple(found),
        missing=tuple(missing),
        verdicts_path=verdicts,
        notes=tuple(notes),
    )


def _verdicts_text(
    ranking: tuple[str, ...], missing: list[tuple[str, str]], notes: tuple[str, ...]
) -> str:
    """The verdict file: the questions already written in, and a row per model.

    The 2026-10-26 session established that the useful format is **free-form, a line or
    two per model**, not a rubric filled in. So the questions are prompts rather than
    fields to score, and there is deliberately nothing numeric to complete -- the suite
    already holds every number, and these are the judgements it cannot make.
    """
    lines = [
        "# Verdicts -- writing, PDF and layout quality",
        "",
        "Only you can fill this in. The evaluation measures whether a document was",
        "accepted, what it cost and how many correction calls it took. It measures **no",
        "prose and no rendering**, so nothing here can be inferred from the table.",
        "",
        "**Until a model has a verdict, it is not eligible for curation.** That is",
        "enforced in code, not by convention.",
        "",
        "Folder names are `<rank>-<model>-<case>`, numbered by the study's own ranking",
        "(cheapest per accepted result first). **If your reading disagrees with that",
        "order, say so plainly** -- that disagreement is exactly what this step exists to",
        "find, and it changes the recommendation.",
        "",
        "The four questions worth answering, per model:",
        "",
        "1. **Would you send it?** yes / no / only after edits. The single most useful",
        "   signal, and the one nothing else here can produce.",
        "2. **Does it read like it was written for this posting**, or generic?",
        "3. **Anything wrong in the PDF** -- clipped text, an orphan heading, odd spacing,",
        "   cramped or oversized type, a section that broke awkwardly across a page?",
        "4. **Anything factually off** -- a claim the profile does not support, a wrong",
        "   date, an employer's wording changed?",
        "",
        "Free-form is fine. If a model is bad for a specific reason, the reason is worth",
        "more than a score.",
        "",
    ]
    if notes:
        lines.append("## Notes on this run")
        lines.append("")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")
    lines.append("---")
    lines.append("")
    for model_id in ranking:
        lines.append(_PROMPT_TEMPLATE.format(model_id=model_id))
    if missing:
        lines.append("---")
        lines.append("")
        lines.append("## Models with nothing to read")
        lines.append("")
        for model_id, reason in missing:
            lines.append(f"- **{model_id}** -- {reason}")
        lines.append("")
    return "\n".join(lines)


def parity_with_verdicts(packet: ReadingPacket, verdicts: dict) -> dict:
    """Which ranked models have a verdict and which do not.

    Returns ``{"with_verdict": (...), "without_verdict": (...), "unreadable": (...)}``.

    A model the packet could not produce documents for is reported as **unreadable**
    rather than as missing a verdict: asking for a quality judgement about a model that
    produced nothing would invite a verdict about the absence of evidence.
    """
    ranked = packet.models()
    unreadable_ids = {model_id for model_id, _ in packet.missing}
    with_verdict, without = [], []
    for model_id in ranked:
        if (verdicts.get(model_id) or "").strip():
            with_verdict.append(model_id)
        else:
            without.append(model_id)
    return {
        "with_verdict": tuple(with_verdict),
        "without_verdict": tuple(without),
        "unreadable": tuple(m for m in ranked if m in unreadable_ids),
    }


def load_verdicts(verdicts_path: Path) -> dict:
    """Read verdicts back from a filled-in ``VERDICTS.md``.

    Parsed from the ``## <model-id>`` headings and the text beneath each, which is the
    format :func:`_verdicts_text` writes. Deliberately forgiving: the owner writes prose,
    and a parser that demanded structure would be asking them to serve the tool.

    A heading whose body is only the unanswered prompt template counts as **no verdict**,
    so an untouched file cannot promote anything.
    """
    text = Path(verdicts_path).read_text(encoding="utf-8")
    verdicts: dict = {}
    current: Optional[str] = None
    body: list[str] = []

    def flush():
        if current is None:
            return
        meaningful = []
        for line in body:
            stripped = line.strip()
            if not stripped or stripped.startswith("---"):
                continue
            # An **untouched** prompt line is dropped whole. Matching the full question is
            # what makes that work: a prefix match leaves the parenthetical guidance
            # looking like an answer.
            if stripped in _PROMPT_LINES:
                continue
            # A prompt line **answered inline** keeps only what follows the question, so
            # "- would send? (yes / no / only after edits): yes" reads back as "yes".
            label = next(
                (q for q in _PROMPT_LINES if stripped.startswith(q)), None
            )
            if label is not None:
                answer = stripped[len(label):].strip()
                if answer:
                    meaningful.append(answer)
                continue
            meaningful.append(stripped)
        verdicts[current] = "\n".join(meaningful).strip()

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            heading = line[3:].strip()
            current = heading if "/" in heading else None
            body = []
        elif current is not None:
            body.append(line)
    flush()

    return {k: v for k, v in verdicts.items() if k}
