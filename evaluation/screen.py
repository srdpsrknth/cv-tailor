"""The screen: a listing record in, a proposed candidate slate out, offline.

**Why this exists.** Curation is two jobs of very different cost. Deciding *which
models are worth paying to measure* is free -- it is arithmetic over a listing -- and
deciding *which of those actually works* costs money per candidate. Running the paid
job on the whole catalogue to discover that most of it was never viable is how a
budget disappears without producing a ranking. The 2026-10-26 study put **8** candidates
forward from **467**; this module is that reduction, written down instead of performed
by hand over a session.

**Rejections are the deliverable, not a by-product.** A screen that returns eight ids
and no reasoning hands the owner a list to take on trust. Every rejection here carries
the rule that produced it and the value that failed, so a person can disagree with a
specific decision rather than with the whole result: "8 of 267, and here are the 259 I
dropped, and why".

**What this module must never become.** It does not rank on quality. It cannot: no
measurement has happened yet, and ADR 0005 forbids a quality claim from a leaderboard.
Everything here is a *filter* -- properties a model must have for the pipeline to be
able to call it at all, plus the owner's recency rule -- and the ordering it produces is
by **price**, which is a fact from the listing, not a judgement about output.

The one thing that looks like a judgement and is not: the slate is capped at
:data:`MAX_SLATE`. That is a budget decision. Eight candidates against three cases is
the $1.65 projection already measured; twenty would be 2.5x the budget for candidates
that the screen has already ranked *below* the ones it kept.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from evaluation.curated_models import MIN_CREATED, NATURAL_COST_ORDER
from evaluation.listing import ListingEntry, ListingRecord

#: The most candidates a run may be asked to measure. Not a preference: the projection
#: is per-candidate, and the owner's cap is per-run. Eight was the 2026-10-26 slate and
#: it projected at $1.6467 against a $5 cap, so eight is a figure with a measured cost
#: behind it rather than a round number.
MAX_SLATE = 8

#: What a typical two-call application run costs in output tokens, used to define the
#: cost tiers below. These are ``evaluation.cases``' measured shape (a CV call at 1,350
#: output tokens plus a letter at 622) -- imported rather than restated, because two
#: copies of this arithmetic is how a set of tiers stops matching the runs it tiers.
def _typical_run_cost(entry: ListingEntry) -> float:
    """USD for one typical two-call run on ``entry``.

    Output-weighted on purpose, and this is a measured property of the pipeline rather
    than a modelling choice: ``curated_models`` records that ranking candidates by
    *input* price is actively misleading here, because this pipeline spends most of its
    budget on output. A tier computed from input rates would put a model that is cheap
    to prompt and expensive to answer in the wrong band.
    """
    from evaluation import cases

    return entry.cost_for(
        cases.CV_INPUT_TOKENS + cases.CL_INPUT_TOKENS,
        cases.CV_OUTPUT_TOKENS + cases.CL_OUTPUT_TOKENS,
    )


#: Rejection rules, in the order they are applied. Each is a name and a one-line reason
#: so a report can group rejections without a caller inventing prose for them.
REJECT_NOT_STRUCTURED = "no-structured-output"
REJECT_CEILING_TOO_LOW = "output-ceiling-too-small"
REJECT_UNPRICED = "no-usable-price"
REJECT_TOO_OLD = "older-than-owner-floor"
REJECT_NO_DATE = "no-usable-creation-date"
REJECT_ROUTING_VARIANT = "routing-variant-not-a-model"
REJECT_NOT_SHORTLISTED = "not-shortlisted"
REJECT_ALREADY_CURATED = "already-the-selected-model"

#: One line per rule, for the report. Kept beside the constants so a new rule cannot be
#: added without a sentence explaining it to whoever reads the output.
REJECTION_REASONS = {
    REJECT_NOT_STRUCTURED: (
        "does not advertise structured_outputs; a model that cannot be relied on for "
        "schema-valid JSON cannot serve this pipeline"
    ),
    REJECT_CEILING_TOO_LOW: (
        "its output ceiling is smaller than a document; the response would be truncated "
        "before it finished"
    ),
    REJECT_UNPRICED: (
        "no usable price in the listing, so the run's headline metric -- cost per "
        "accepted result -- would be an invented fallback figure"
    ),
    REJECT_TOO_OLD: (
        "created before the owner's floor; the cheapest tiers of a catalogue are cheap "
        "because they are old"
    ),
    REJECT_NO_DATE: (
        "no usable creation date, so the recency floor cannot be shown to be satisfied"
    ),
    REJECT_ROUTING_VARIANT: (
        "a routing variant of another entry (:batch, :free, :extended, or a ~latest "
        "alias) rather than a distinct model; measuring one variant of a model against "
        "another measures the route, not the model"
    ),
    REJECT_NOT_SHORTLISTED: (
        "passed every filter but was not one of the models selected for the slate. This "
        "is a SHORTLISTING decision, not a defect: the model remains a viable candidate "
        "for a later run"
    ),
    REJECT_ALREADY_CURATED: (
        "already the selected model, so it is kept as the control rather than as a "
        "challenger"
    ),
}


@dataclass(frozen=True)
class Rejection:
    """One model the screen dropped, the rule that dropped it, and the value behind it.

    The ``observed`` field is what makes a rejection arguable. "Rejected: too old" is a
    verdict; "rejected: created 2024-10-22, floor is 2025-10-01" is a fact a reader can
    check and overrule.
    """

    model_id: str
    rule: str
    observed: str

    @property
    def reason(self) -> str:
        return REJECTION_REASONS.get(self.rule, self.rule)

    def describe(self) -> str:
        return f"{self.model_id}: {self.reason} (observed: {self.observed})"


@dataclass(frozen=True)
class DialectHint:
    """The schema dialect a candidate will *probably* need, with its basis stated.

    **This is a hint and never a measurement.** ADR 0016 requires every per-candidate
    adaptation to record the **measured** error that forced it, and
    ``candidate_inputs.CandidateInputs`` enforces that by refusing a non-default dialect
    with no rationale. A hint derived from a vendor name cannot satisfy that rule, and
    it must not be able to pretend to -- :attr:`basis` says where it came from, and
    :func:`is_assumed` distinguishes the two so a caller can label it honestly.

    It exists because the alternative is worse. Three provider families demand mutually
    incompatible schemas, and the 2026-10-26 study spent real money discovering that
    one family at a time. Carrying that knowledge forward as a *labelled guess* saves a
    future session from re-buying it, while the ADR's rule still requires the run to
    confirm it before anything is recorded as measured.
    """

    dialect: str
    basis: str
    #: True when derived from a vendor name rather than from an observed failure.
    assumed: bool = True

    def is_assumed(self) -> bool:
        return self.assumed


#: Vendor prefixes to a likely dialect, from the errors measured on 2026-10-26/27
#: (ADR 0016). Prefix matching is deliberate: the dialect is a property of the
#: *provider family serving the route*, and the family is what the prefix names.
#:
#: ``openai`` -> strict: OpenAI's strict mode requires ``additionalProperties: false``
#: on every object and cannot express a free-form map.
#: ``anthropic`` -> Vertex: rejects a schema with more than 24 optional parameters.
#: ``google`` -> Gemini: rejects ``additionalProperties`` outright.
DIALECT_HINTS = {
    "openai/": ("strict", "OpenAI strict mode requires additionalProperties: false"),
    "anthropic/": (
        "anthropic-vertex",
        "Anthropic behind Vertex rejects more than 24 optional parameters",
    ),
    "google/": (
        "gemini",
        "Gemini rejects additionalProperties outright",
    ),
}


def dialect_hint_for(model_id: str) -> Optional[DialectHint]:
    """The likely dialect for ``model_id``, or ``None`` when the family is unknown.

    ``None`` is the honest answer for an unrecognised vendor, and it is preferable to
    the default dialect: defaulting would assert "this needs no adaptation" about a
    family nobody has measured, which is a stronger claim than "we do not know".
    """
    lowered = model_id.lower()
    for prefix, (dialect, basis) in DIALECT_HINTS.items():
        if lowered.startswith(prefix):
            return DialectHint(dialect=dialect, basis=basis, assumed=True)
    return None


@dataclass(frozen=True)
class Candidate:
    """One proposed candidate: the listing entry plus what the screen knows about it."""

    entry: ListingEntry
    typical_run_cost: float
    tier: str
    dialect_hint: Optional[DialectHint] = None

    @property
    def id(self) -> str:
        return self.entry.id

    def describe(self) -> str:
        hint = (
            self.dialect_hint.dialect if self.dialect_hint else "unknown-family"
        )
        assumed = " (assumed)" if self.dialect_hint and self.dialect_hint.is_assumed() else ""
        return (
            f"{self.id:44} {self.tier:>9} "
            f"${self.entry.prompt:8.3f} ${self.entry.completion:8.3f} "
            f"${self.typical_run_cost:7.5f}  dialect={hint}{assumed}"
        )


@dataclass
class Slate:
    """The screen's result: what is proposed, and everything it dropped with a reason.

    Both halves are first-class. A caller that reported only :attr:`candidates` would
    reproduce the failure this module exists to prevent -- a shortlist presented as
    though it were the whole consideration.
    """

    candidates: tuple[Candidate, ...] = ()
    rejections: tuple[Rejection, ...] = ()
    library_size: int = 0
    floor: str = MIN_CREATED
    cap: int = MAX_SLATE
    #: The control: the model currently shipped, kept so every challenger is measured
    #: against something real rather than against a number on a leaderboard. Absent
    #: when it is not in the record, which is itself reported rather than hidden.
    control: Optional[Candidate] = None

    @property
    def considered(self) -> int:
        return len(self.candidates) + len(self.rejections)

    def rejected_ids(self) -> tuple[str, ...]:
        return tuple(r.model_id for r in self.rejections)

    def rejections_by_rule(self) -> dict[str, tuple[Rejection, ...]]:
        """Rejections grouped by rule, so a report reads as reasons rather than a list."""
        grouped: dict[str, list[Rejection]] = {}
        for rejection in self.rejections:
            grouped.setdefault(rejection.rule, []).append(rejection)
        return {rule: tuple(items) for rule, items in grouped.items()}

    def has_cost_spread(self) -> bool:
        """Whether the slate spans genuinely different cost levels.

        The owner's requirement was a set spanning performance *and* cost. A slate of
        eight near-identical prices satisfies "small" while failing the instruction, and
        that is checkable before any money is spent. Measured on the **run**, not on the
        input rate, for the reason ``curated_models.has_cost_spread`` records.
        """
        if len(self.candidates) < 2:
            return False
        costs = [c.typical_run_cost for c in self.candidates]
        return max(costs) >= 5 * min(costs)

    def describe(self) -> str:
        lines = [
            f"Candidate screen: {len(self.candidates)} proposed from "
            f"{self.considered} considered ({self.library_size} in the listing record).",
            f"  floor {self.floor}   slate cap {self.cap}   "
            f"cost spread {'yes' if self.has_cost_spread() else 'NO'}",
            "",
        ]
        if self.control is not None:
            lines.append("Control (currently shipped, kept for comparison):")
            lines.append(f"  {self.control.describe()}")
            lines.append("")
        lines.append(f"Proposed ({len(self.candidates)}):")
        for candidate in self.candidates:
            lines.append(f"  {candidate.describe()}")
        lines.append("")
        grouped = self.rejections_by_rule()
        lines.append(f"Rejected ({len(self.rejections)}), by rule:")
        for rule, items in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"  {rule} -- {len(items)} model(s)")
            lines.append(f"    {REJECTION_REASONS.get(rule, rule)}")
            for rejection in items[:6]:
                lines.append(f"      - {rejection.model_id} ({rejection.observed})")
            if len(items) > 6:
                lines.append(f"      ... and {len(items) - 6} more")
        lines.append("")
        lines.append(
            "Nothing here is a quality ranking. Candidates are ordered by price, which "
            "is a fact from the listing; only a measured run can rank them."
        )
        return "\n".join(lines)


def is_routing_variant(model_id: str) -> bool:
    """Whether ``model_id`` is a *route* on a model rather than a model.

    OpenRouter exposes several ways to reach one model, and they are not alternatives
    worth measuring against each other:

    * ``:batch`` -- the asynchronous bulk route, with its own price and its own
      latency, which this pipeline cannot use (it needs a document back in a request);
    * ``:free`` -- a rate-limited promotional route, which would measure a queue;
    * ``:extended`` / ``:thinking`` -- a different reasoning configuration of the same
      weights;
    * ``~vendor/model-latest`` -- an alias that **re-points as the vendor ships**, so a
      ranking recorded against it stops describing a fixed thing.

    Two consequences made this worth a rule rather than a footnote. The 2026-10-30
    screen found **55** ``:batch`` entries and **18** tilde aliases among the survivors,
    and the ``:batch`` route of a model is often *cheaper* than the model -- so a
    cheapest-first slate filled up with routes this pipeline cannot even call, and the
    one model that would have been proposed on merit was pushed out by its own
    bulk-priced shadow.
    """
    lowered = model_id.lower()
    if lowered.startswith("~"):
        return True
    stem = lowered.rsplit(":", 1)
    return len(stem) == 2 and stem[1] in ROUTING_VARIANT_SUFFIXES


#: The suffixes that name a route rather than a model. A suffix outside this set is left
#: alone deliberately: an unrecognised colon suffix might be a model's own versioning.
ROUTING_VARIANT_SUFFIXES = frozenset(
    {"batch", "free", "extended", "thinking", "online", "nitro"}
)


def _select_across_costs(
    survivors: list[ListingEntry], cap: int
) -> tuple[list[ListingEntry], list[ListingEntry]]:
    """Choose ``cap`` candidates: cheapest-first, with the cost range kept represented.

    **Two wrong answers were measured here before this one, and both are worth recording
    because each looked reasonable.**

    *Taking the cheapest ``cap``* was the first implementation. Run against the real
    record it produced eight models inside the bottom 0.2% of the price range and
    reported ``cost spread NO`` -- correctly, because it held eight economy models and no
    frontier one. That fails the owner's standing requirement that a set span performance
    *and* cost (ADR 0005), and it fails it invisibly, since every entry looks defensible.

    *Strict round-robin over the three bands* was the second. It fixed the spread and
    broke the slate: the frontier band is mostly ``*-pro`` models at $0.41-$0.71 **per
    run**, roughly 200x the selected model, and the round-robin dutifully filled half the
    slate with them. Those are not plausible candidates for a two-page CV; a study that
    spends its budget there answers a question nobody asked.

    **So the bias is deliberately towards cheap, with one guard against blindness.** The
    slate is filled cheapest-first, and if that leaves the dearest band unrepresented, its
    *cheapest* member replaces the slate's most expensive entry. One frontier candidate,
    not half the slate -- enough that "is a 100x dearer model worth it" is asked, without
    letting price-of-entry decide the slate.

    Returns ``(kept, not_shortlisted)``. The second is *not* a rejection on merit and the
    caller must present it as such.
    """
    ordered = sorted(survivors, key=lambda e: (_typical_run_cost(e), e.id))
    if cap >= len(ordered):
        return ordered, []

    kept = list(ordered[:cap])

    costs = [_typical_run_cost(e) for e in ordered]
    cheapest, dearest = costs[0], costs[-1]
    bands = {tier: [e for e in ordered if _tier_for(_typical_run_cost(e), cheapest, dearest) == tier]
             for tier in NATURAL_COST_ORDER}
    dearest_band = bands[NATURAL_COST_ORDER[-1]]

    if dearest_band and not any(e in kept for e in dearest_band):
        # No expensive candidate survived the cheapest-first cut: swap one in, at the
        # cost of the slate's dearest entry, so the comparison spans the range.
        replacement = dearest_band[0]
        dropped = max(kept, key=lambda e: (_typical_run_cost(e), e.id))
        kept = [e for e in kept if e is not dropped] + [replacement]

    kept.sort(key=lambda e: (_typical_run_cost(e), e.id))
    kept_ids = {e.id for e in kept}
    not_shortlisted = [e for e in ordered if e.id not in kept_ids]
    return kept, not_shortlisted


def _tier_for(cost: float, cheapest: float, dearest: float) -> str:
    """Which cost band ``cost`` falls in, relative to the candidates considered.

    Relative rather than absolute thresholds, because this catalogue's price level moves
    -- the 2026-10-30 read returned 456 models where 2026-10-26 returned 467, and
    ``curated_models`` records four prices moving within a single day. Fixed dollar
    boundaries would silently mislabel every model the next time the market shifted.
    """
    if dearest <= cheapest:
        return NATURAL_COST_ORDER[0]
    position = (cost - cheapest) / (dearest - cheapest)
    if position < 1 / 3:
        return NATURAL_COST_ORDER[0]
    if position < 2 / 3:
        return NATURAL_COST_ORDER[1]
    return NATURAL_COST_ORDER[2]


def screen_record(
    record: ListingRecord,
    *,
    control_id: Optional[str] = None,
    cap: int = MAX_SLATE,
    exclude: tuple[str, ...] = (),
    floor: str = MIN_CREATED,
) -> Slate:
    """Reduce a listing record to a proposed slate, with every rejection reasoned.

    Args:
        record: the committed listing reading to screen.
        control_id: the currently shipped model, kept identified rather than proposed.
            It is not a challenger, so measuring it again only prices the incumbent --
            useful, but a different question from "what should replace it".
        cap: the most challengers to propose.
        exclude: ids to drop outright, for a caller that has already measured them.
        floor: the recency floor. Defaults to the owner's recorded rule.

    Offline, deterministic, and free. It reads a file the repository already has; there
    is no parameter here that could cause a call, which is the property that makes it
    safe to put in front of a spend decision.
    """
    rejections: list[Rejection] = []
    survivors: list[ListingEntry] = []
    control: Optional[Candidate] = None

    for entry in record.entries:
        # Order matters for the report's readability, not for correctness: the first
        # rule that fails is the one recorded, so a model is not listed under four
        # headings at once.
        if not entry.created:
            rejections.append(Rejection(entry.id, REJECT_NO_DATE, "created field absent"))
            continue
        if entry.created < floor:
            rejections.append(Rejection(entry.id, REJECT_TOO_OLD, f"created {entry.created}"))
            continue
        if not entry.structured_outputs:
            rejections.append(
                Rejection(entry.id, REJECT_NOT_STRUCTURED, "structured_outputs absent")
            )
            continue
        if entry.max_completion_tokens < _min_ceiling():
            rejections.append(
                Rejection(
                    entry.id,
                    REJECT_CEILING_TOO_LOW,
                    f"max_completion_tokens {entry.max_completion_tokens}",
                )
            )
            continue
        if entry.prompt <= 0 or entry.completion <= 0:
            rejections.append(
                Rejection(
                    entry.id,
                    REJECT_UNPRICED,
                    f"prompt {entry.prompt} completion {entry.completion}",
                )
            )
            continue
        if is_routing_variant(entry.id):
            rejections.append(
                Rejection(entry.id, REJECT_ROUTING_VARIANT, "route suffix or alias")
            )
            continue
        if entry.id in exclude:
            rejections.append(
                Rejection(entry.id, REJECT_NOT_SHORTLISTED, "excluded by the caller")
            )
            continue
        if control_id is not None and entry.id == control_id:
            # Kept, but as the control rather than as a challenger.
            continue
        survivors.append(entry)

    # Shortlist across the cost range rather than taking the cheapest `cap`. See
    # `_select_across_costs` for the measurement that forced this.
    kept, not_shortlisted = _select_across_costs(survivors, cap)
    for entry in not_shortlisted:
        rejections.append(
            Rejection(
                entry.id,
                REJECT_NOT_SHORTLISTED,
                f"run ${_typical_run_cost(entry):.5f}, {len(survivors)} passed the filters",
            )
        )

    costs = [_typical_run_cost(e) for e in kept] or [0.0]
    cheapest, dearest = min(costs), max(costs)
    candidates = tuple(
        Candidate(
            entry=entry,
            typical_run_cost=_typical_run_cost(entry),
            tier=_tier_for(_typical_run_cost(entry), cheapest, dearest),
            dialect_hint=dialect_hint_for(entry.id),
        )
        for entry in kept
    )

    if control_id is not None:
        entry = record.find(control_id)
        if entry is not None:
            cost = _typical_run_cost(entry)
            control = Candidate(
                entry=entry,
                typical_run_cost=cost,
                tier=_tier_for(cost, cheapest, dearest) if candidates else "control",
                dialect_hint=dialect_hint_for(entry.id),
            )

    return Slate(
        candidates=candidates,
        rejections=tuple(rejections),
        library_size=len(record.entries),
        floor=floor,
        cap=cap,
        control=control,
    )


def _min_ceiling() -> int:
    """The ceiling filter, read from :mod:`evaluation.listing` rather than restated."""
    from evaluation.listing import MIN_MAX_COMPLETION_TOKENS

    return MIN_MAX_COMPLETION_TOKENS
