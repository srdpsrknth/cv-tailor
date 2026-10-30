"""Detect what changed in the catalogue, and propose -- never apply -- a curation diff.

**Two jobs, both offline, neither of which can spend.**

:func:`detect_changes` answers *"is a re-curation worth doing yet?"* by diffing a fresh
listing against the committed record: models added, models repriced, models withdrawn.
This is the only part of the curation workflow that *could* have been automatic, and it
is deliberately not: a provider's routine catalogue churn would then trigger spend
without anyone deciding to. Detection reports, and a person decides.

:func:`propose_curation` turns a finished run into a **proposal artefact** -- the ranked
table, the diff it would make to ``curated_models.py`` and ``candidate_inputs.py``, and a
line of rationale per entry. It writes nothing.

**Why the proposal is inert, and why that is not timidity.** The last study's outcome was
the owner picking a winner, rejecting seven, and editing code by hand. An automatic
replacement would mean an automated step deleting the only model production uses, chosen
on measurements that measure **none** of writing, PDF or layout quality -- the three the
owner reserved for themselves (ADR 0014, ADR 0016). The suite's acceptance gate is real
and the cost metric is real; neither is a quality verdict on prose. So the artefact is a
diff a person reads, and applying it is a deliberate edit with its own commit, exactly as
``e53ef8a`` was.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from evaluation.listing import ListingEntry, ListingRecord, _close
from evaluation.screen import _typical_run_cost


@dataclass(frozen=True)
class Change:
    """One model whose listing entry changed between two reads."""

    model_id: str
    kind: str
    detail: str

    def describe(self) -> str:
        return f"{self.kind:12} {self.model_id}: {self.detail}"


#: The kinds of change a diff reports. ``added`` and ``withdrawn`` are structural;
#: ``repriced`` is the one ADR 0005 calls a maintenance obligation, and the one with
#: measured evidence behind it -- four entries moved between two reads on one day.
CHANGE_ADDED = "added"
CHANGE_WITHDRAWN = "withdrawn"
CHANGE_REPRICED = "repriced"
CHANGE_CAPABILITY = "capability"
CHANGE_RENAMED_DATE = "recreated"


@dataclass
class Detection:
    """What a fresh listing says that the committed record does not.

    :attr:`checked` is the list of curated ids whose price was specifically compared, and
    it exists so "we checked and nothing moved" is a claim with a scope rather than a
    silence.
    """

    previous_read_on: str = ""
    current_read_on: str = ""
    changes: tuple[Change, ...] = ()
    checked: tuple[str, ...] = ()
    previous_count: int = 0
    current_count: int = 0

    @property
    def any_change(self) -> bool:
        return bool(self.changes)

    def by_kind(self, kind: str) -> tuple[Change, ...]:
        return tuple(c for c in self.changes if c.kind == kind)

    def touches(self, model_id: str) -> bool:
        return any(c.model_id == model_id for c in self.changes)

    def describe(self) -> str:
        lines = [
            f"Catalogue diff: {self.previous_read_on or 'unknown'} -> "
            f"{self.current_read_on or 'unknown'}",
            f"  {self.previous_count} -> {self.current_count} models in the record",
            "",
        ]
        if not self.changes:
            lines.append("No changes in the models this record covers.")
        else:
            for kind in (CHANGE_ADDED, CHANGE_REPRICED, CHANGE_WITHDRAWN,
                         CHANGE_CAPABILITY, CHANGE_RENAMED_DATE):
                items = self.by_kind(kind)
                if items:
                    lines.append(f"{kind} ({len(items)}):")
                    for change in items:
                        lines.append(f"  {change.describe()}")
            lines.append("")
        lines.append(
            f"Checked {len(self.checked)} curated id(s) specifically: "
            f"{', '.join(self.checked) if self.checked else 'none'}"
        )
        lines.append("")
        lines.append(
            "This is a REPORT. Nothing was changed and nothing was spent: a re-curation "
            "needs an explicit decision, because a provider's routine catalogue churn "
            "must not be able to trigger spending."
        )
        return "\n".join(lines)


def detect_changes(
    previous: ListingRecord, current: ListingRecord, *, watch: tuple[str, ...] = ()
) -> Detection:
    """Diff two listing records. Offline, deterministic, and free.

    Args:
        previous: the committed record.
        current: a freshly read one.
        watch: curated ids to compare even if the record's other checks would pass them
            by. Reported in :attr:`Detection.checked`, so a negative result is scoped
            rather than assumed to cover everything.

    A change of ``structured_outputs`` or of the output ceiling is reported separately
    from a price change, because it is a different kind of fact: a price change moves the
    ranking, while losing structured output **disqualifies** the model outright. Folding
    them into one "changed" bucket would hide the second behind the first.
    """
    old = previous.by_id()
    new = current.by_id()

    changes: list[Change] = []
    for model_id in sorted(set(new) - set(old)):
        changes.append(Change(model_id, CHANGE_ADDED, "not in the previous record"))
    for model_id in sorted(set(old) - set(new)):
        changes.append(
            Change(model_id, CHANGE_WITHDRAWN, "absent from the new record")
        )
    for model_id in sorted(set(old) & set(new)):
        before, after = old[model_id], new[model_id]
        if not _close(before.prompt, after.prompt) or not _close(
            before.completion, after.completion
        ):
            changes.append(
                Change(
                    model_id,
                    CHANGE_REPRICED,
                    f"${before.prompt:.4f}/${before.completion:.4f} -> "
                    f"${after.prompt:.4f}/${after.completion:.4f} per 1M",
                )
            )
        if before.structured_outputs != after.structured_outputs:
            changes.append(
                Change(
                    model_id,
                    CHANGE_CAPABILITY,
                    f"structured_outputs {before.structured_outputs} -> "
                    f"{after.structured_outputs}",
                )
            )
        if before.max_completion_tokens != after.max_completion_tokens:
            changes.append(
                Change(
                    model_id,
                    CHANGE_CAPABILITY,
                    f"output ceiling {before.max_completion_tokens} -> "
                    f"{after.max_completion_tokens}",
                )
            )
        if before.created != after.created and after.created:
            changes.append(
                Change(
                    model_id,
                    CHANGE_RENAMED_DATE,
                    f"created {before.created or 'absent'} -> {after.created}",
                )
            )

    return Detection(
        previous_read_on=previous.read_on,
        current_read_on=current.read_on,
        changes=tuple(changes),
        checked=tuple(watch),
        previous_count=len(previous.entries),
        current_count=len(current.entries),
    )


# --- the proposal ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProposalEntry:
    """One model in a proposed curation, with the evidence behind it.

    :attr:`verdict` is the owner's, and it is **not** derivable from the metrics. The
    fields beside it are what the suite measured; writing and layout quality are not
    among them.
    """

    model_id: str
    accepted: int
    attempted: int
    cost_per_accepted: Optional[float]
    correction_calls: int = 0
    dialect: str = ""
    verdict: str = ""
    notes: str = ""

    @property
    def acceptance_rate(self) -> float:
        return self.accepted / self.attempted if self.attempted else 0.0

    def is_disqualified(self, *, minimum_rate: float, empty_if_no_accept: bool = True):
        """Why this entry cannot be curated, or ``None`` if nothing disqualifies it.

        The three disqualifiers are the owner's settled answer to "what makes a result a
        failure rather than a ranking":

        1. **acceptance below the floor** -- anything worse than the shipped model's is
           not a candidate, whatever its price;
        2. **accepting nothing at all** -- which the floor already covers, but named
           separately because it is the case where ``cost_per_accepted`` is ``None`` and
           a report must never print a flattering ``0.0`` in its place;
        3. **no verdict from the owner** -- the suite measures no prose and no rendering,
           so a measured acceptance rate is not a quality verdict.

        Deliberately **not** a disqualifier: correction calls. A model that needs them is
        neither cheap nor out; it is simply more expensive, and ``cost_per_accepted``
        already reports that.
        """
        # "Accepted nothing" is checked **before** the rate, and the order is load-bearing
        # rather than stylistic. A model at 0/3 fails the rate test too, so checking the
        # rate first reports it as "0% below the floor" and the distinct fact -- that it
        # has no cost per accepted result at all, and a report must never print a
        # flattering 0.0 in its place -- never surfaces. Found by running the tests.
        if self.accepted == 0 and self.attempted and empty_if_no_accept:
            return "accepted nothing, so it has no cost per accepted result"
        if self.attempted and self.acceptance_rate < minimum_rate:
            return (
                f"accepted {self.accepted}/{self.attempted} "
                f"({self.acceptance_rate:.0%}), below the {minimum_rate:.0%} floor"
            )
        if not self.verdict.strip():
            return (
                "no writing/PDF/layout verdict from the owner, which this suite does "
                "not measure"
            )
        return None


@dataclass
class CurationProposal:
    """A proposed curation: the ranking, the disqualifications, and the diff.

    Written to be read by a person, and **inert**. :meth:`diff_for_curated_models` and
    :meth:`diff_for_candidate_inputs` produce *text*, never an edit; applying them is a
    deliberate commit.
    """

    entries: tuple[ProposalEntry, ...] = ()
    minimum_rate: float = 2 / 3
    current_model: str = ""
    run_reference: str = ""
    #: Notes about the run itself -- a 429 storm, a ceiling that emptied a candidate --
    #: which belong beside the numbers because they explain them.
    run_notes: tuple[str, ...] = ()

    def ranked(self) -> tuple[ProposalEntry, ...]:
        """Accepted first, cheapest per accepted result first; the rest after.

        A model that accepted nothing sorts last regardless of price, for the reason
        ``metrics.rank`` gives: it is not a cheap option, it is not an option.
        """
        def key(entry: ProposalEntry):
            cost = entry.cost_per_accepted
            return (entry.accepted == 0, cost is None, cost if cost is not None else 0.0)

        return tuple(sorted(self.entries, key=key))

    def eligible(self) -> tuple[ProposalEntry, ...]:
        """Entries nothing disqualifies."""
        return tuple(e for e in self.ranked() if e.is_disqualified(
            minimum_rate=self.minimum_rate) is None)

    def winner(self) -> Optional[ProposalEntry]:
        """The cheapest eligible entry that beats the shipped model, if any.

        ``None`` means "keep what we have", which is a real outcome and the common one:
        a re-curation that finds nothing better is a successful re-curation.
        """
        current = next(
            (e for e in self.entries if e.model_id == self.current_model), None
        )
        for entry in self.eligible():
            if entry.model_id == self.current_model:
                continue
            if current is None or current.cost_per_accepted is None:
                return entry
            if (
                entry.cost_per_accepted is not None
                and entry.cost_per_accepted < current.cost_per_accepted
            ):
                return entry
        return None

    def describe(self) -> str:
        lines = [
            "Curation proposal -- FOR REVIEW. Nothing has been changed.",
            f"  run: {self.run_reference or 'unspecified'}",
            f"  acceptance floor: {self.minimum_rate:.0%}",
            f"  current model: {self.current_model or 'unspecified'}",
            "",
        ]
        header = (
            f"  {'model':34} {'acc':>6} {'/ACCEPTED':>11} {'corr':>5}  "
            f"{'dialect':<16} status"
        )
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for entry in self.ranked():
            cost = (
                f"${entry.cost_per_accepted:.5f}"
                if entry.cost_per_accepted is not None
                else "none accepted"
            )
            disqualified = entry.is_disqualified(minimum_rate=self.minimum_rate)
            status = "ELIGIBLE" if disqualified is None else f"OUT: {disqualified}"
            lines.append(
                f"  {entry.model_id[:34]:34} "
                f"{entry.accepted}/{entry.attempted:<4} {cost:>11} "
                f"{entry.correction_calls:5}  {entry.dialect or '-':<16} {status}"
            )
        if self.run_notes:
            lines.append("")
            lines.append("Notes on the run:")
            for note in self.run_notes:
                lines.append(f"  - {note}")
        lines.append("")
        winner = self.winner()
        if winner is None:
            lines.append(
                "RECOMMENDATION: keep the current model. Nothing eligible is cheaper "
                "per accepted result, which is a real outcome and not a failure."
            )
        else:
            lines.append(
                f"RECOMMENDATION: consider {winner.model_id} "
                f"(${winner.cost_per_accepted:.5f} per accepted result). "
                "This is a recommendation to review, not a switch."
            )
        lines.append("")
        lines.append(
            "WHAT THIS DOES NOT MEASURE: writing quality, PDF quality and layout "
            "quality. The suite records acceptance, cost and correction calls only. The "
            "owner reads the accepted documents and makes those judgements; an entry "
            "with no verdict from them is listed as OUT for that reason and not for any "
            "measured defect."
        )
        return "\n".join(lines)

    def diff_for_curated_models(self) -> str:
        """The edit ``evaluation/curated_models.py`` would need. **Text, not an edit.**

        Emitted rather than applied so it can be read in a review before anything
        changes, and so applying it is a deliberate act with its own commit -- which is
        how ``e53ef8a`` shipped the current model.
        """
        lines = [
            "# Proposal only -- this text has NOT been applied.",
            "# Applying it is a curation decision (ADR 0014, ADR 0016) and requires the",
            "# owner's writing/PDF/layout verdict, which the evaluation does not measure.",
            "",
        ]
        winner = self.winner()
        if winner is None:
            lines.append("# No change proposed: keep the current model.")
            return "\n".join(lines)

        lines.append(f'# Replace CURATED_MODELS with a single entry for {winner.model_id}:')
        lines.append("CURATED_MODELS: tuple[CuratedModel, ...] = (")
        lines.append(f'    CuratedModel(')
        lines.append(f'        id="{winner.model_id}",')
        lines.append('        tier="economy",  # set from the measured run cost')
        lines.append(f'        label="{winner.model_id} (selected)",')
        lines.append('        guidance=(  # fill in from the owner\'s reading'),
        lines.append('            "..."')
        lines.append('        ),')
        lines.append('        input_per_1m=0.0,  # from the listing record')
        lines.append('        output_per_1m=0.0,')
        lines.append('        created="",  # from the listing record')
        lines.append(f'        accepted={winner.accepted},')
        lines.append(f'        attempted={winner.attempted},')
        lines.append(f'        cost_per_accepted={winner.cost_per_accepted!r},')
        lines.append('        measured_notes=(')
        lines.append(f'            {winner.notes!r}')
        lines.append('        ),')
        lines.append('    ),')
        lines.append(')')
        lines.append('')
        lines.append('# Also required: the id must be priced on the OpenRouter route in')
        lines.append('# services/pricing.PRICING, or price_for silently borrows the fallback')
        lines.append('# rate and the ranking becomes fiction. tests/test_pricing.py asserts it.')
        return "\n".join(lines)

    def diff_for_candidate_inputs(self) -> str:
        """The edit ``evaluation/candidate_inputs.py`` would need. Text, not an edit.

        A candidate that needed an adaptation must carry the **measured** error that
        forced it (ADR 0016) -- so this emits a skeleton with the dialect observed on the
        run, and the rationale deliberately left for a person to fill from the error.
        """
        winner = self.winner()
        lines = [
            "# Proposal only -- this text has NOT been applied.",
            "#",
            "# ADR 0016: every per-candidate adaptation must record the MEASURED error",
            "# that forced it. A dialect copied from a screen hint is not a measurement,",
            "# and CandidateInputs refuses a non-default dialect with no rationale.",
            "",
        ]
        if winner is None:
            lines.append("# No change proposed.")
            return "\n".join(lines)
        lines.append("CANDIDATE_INPUTS: tuple[CandidateInputs, ...] = (")
        lines.append("    CandidateInputs(")
        lines.append(f'        model_id="{winner.model_id}",')
        lines.append(f'        dialect="{winner.dialect or "DIALECT_GEMINI"}",')
        lines.append('        rationale=(  # REQUIRED: paste the measured error here')
        lines.append('            "..."')
        lines.append('        ),')
        lines.append('    ),')
        lines.append(")")
        return "\n".join(lines)


def proposal_from_scores(
    scores: list,
    *,
    current_model: str = "",
    minimum_rate: float = 2 / 3,
    dialects: Optional[dict] = None,
    run_reference: str = "",
    run_notes: tuple[str, ...] = (),
) -> CurationProposal:
    """Build a proposal from ``evaluation.metrics.ModelScore`` objects.

    The scores carry the measured figures; the **verdict** is not among them and is never
    inferred here. An entry with no verdict is reported as disqualified *for that reason*,
    which is the honest encoding: the run is complete and the curation is not.

    Args:
        scores: ``ModelScore`` objects, one per measured candidate.
        current_model: the model currently shipped, so the recommendation has a baseline
            rather than being an absolute claim.
        minimum_rate: the acceptance floor (the owner's 2/3).
        dialects: model id -> the dialect it was asked in, from the run. Recorded so a
            result is attributable to the model *or* to its inputs (ADR 0016).
        run_reference: where the run's artefacts are, so a reader can go and look.
        run_notes: anything about the run that explains the numbers -- a 429 storm, a
            raised ceiling. Emitted beside the table rather than lost.
    """
    dialects = dialects or {}
    entries = tuple(
        ProposalEntry(
            model_id=score.model_id,
            accepted=score.accepted,
            attempted=score.attempted,
            cost_per_accepted=score.cost_per_accepted,
            correction_calls=score.correction_calls,
            dialect=dialects.get(score.model_id, ""),
        )
        for score in scores
    )
    return CurationProposal(
        entries=entries,
        minimum_rate=minimum_rate,
        current_model=current_model,
        run_reference=run_reference,
        run_notes=tuple(run_notes),
    )


def apply_verdicts(
    proposal: CurationProposal, verdicts: dict
) -> CurationProposal:
    """A copy of ``proposal`` with the owner's verdicts attached.

    ``verdicts`` maps a model id to the owner's written judgement of its **writing, PDF
    and layout quality** -- the three the suite does not measure. This is the only way an
    entry becomes eligible, and it is why the workflow cannot complete without a person:
    there is no code path from a measurement to a verdict, by construction.

    A blank or whitespace-only verdict is treated as absent rather than as acceptance, so
    a placeholder cannot promote an entry.
    """
    updated = tuple(
        ProposalEntry(
            model_id=entry.model_id,
            accepted=entry.accepted,
            attempted=entry.attempted,
            cost_per_accepted=entry.cost_per_accepted,
            correction_calls=entry.correction_calls,
            dialect=entry.dialect,
            verdict=(verdicts.get(entry.model_id) or "").strip(),
            notes=entry.notes,
        )
        for entry in proposal.entries
    )
    return CurationProposal(
        entries=updated,
        minimum_rate=proposal.minimum_rate,
        current_model=proposal.current_model,
        run_reference=proposal.run_reference,
        run_notes=proposal.run_notes,
    )
