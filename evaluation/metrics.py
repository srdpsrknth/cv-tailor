"""The metrics ADR 0005 names, and the one that matters most.

The eight criteria, and what each is actually measuring here:

| Criterion | How it is observed |
|---|---|
| accuracy | the factual gate's verdict, and every employer/date preserved |
| completeness | every profile employer present in the accepted CV |
| relevance | whether the posting's terms appear in the tailored wording |
| writing quality | objective proxies only -- length budgets, bullet count, no orphan headings |
| structured-output success | whether the response parsed and validated without correction |
| unnecessary claims | banned tools, sponsorship in a CV, unearned completion claims |
| correction attempts | calls beyond the first per document |
| **cost per accepted result** | total spend divided by *accepted* runs -- see below |

**Why cost per accepted result is the headline.** Cost per call flatters a model that
is cheap per token and fails the gate, because the failures are where the cost goes:
a draft that fails validation is retried twice more, so a model that fails once has
already cost three times its per-call price and produced nothing usable. Dividing by
*accepted* results -- not by attempts -- makes that visible instead of hiding it. It
is the difference between "cheap" and "cheap when it works".

Writing quality is deliberately **not** scored by a model here. A model judging prose
would add cost, variance and a second thing to distrust; the objective proxies above
are what can be asserted reproducibly, and the final judgement in ADR 0005's list is
the owner's, made by reading the accepted documents.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CaseResult:
    """What happened on one case, for one model.

    ``accepted`` is the gate's verdict, not the runner's opinion: a run is accepted
    only if the pipeline returned a validated document.
    """

    model_id: str
    case_name: str
    accepted: bool
    cost_usd: float = 0.0
    calls: int = 0
    #: Calls spent beyond the minimum -- the correction loop's cost, made visible.
    correction_calls: int = 0
    structured_output_ok: bool = True
    facts_ok: bool = True
    completeness_ok: bool = True
    letter_word_count: Optional[int] = None
    letter_within_budget: Optional[bool] = None
    cv_page_count: Optional[int] = None
    error: Optional[str] = None

    @property
    def cost_per_call(self) -> float:
        return self.cost_usd / self.calls if self.calls else 0.0


@dataclass
class ModelScore:
    """One model's aggregate across every case.

    The two cost figures are kept side by side on purpose: the gap between them *is*
    the finding, and a summary that showed only one would hide it.
    """

    model_id: str
    label: str = ""
    results: list = field(default_factory=list)

    @property
    def attempted(self) -> int:
        return len(self.results)

    @property
    def accepted(self) -> int:
        return sum(1 for r in self.results if r.accepted)

    @property
    def acceptance_rate(self) -> float:
        return self.accepted / self.attempted if self.attempted else 0.0

    @property
    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.results)

    @property
    def cost_per_attempt(self) -> float:
        return self.total_cost_usd / self.attempted if self.attempted else 0.0

    @property
    def cost_per_accepted(self) -> Optional[float]:
        """The headline metric. ``None`` when nothing was accepted.

        ``None`` rather than ``inf`` or zero: a model that accepted nothing has no
        meaningful cost per accepted result, and reporting 0.0 would make the worst
        possible performer look like the cheapest.
        """
        if not self.accepted:
            return None
        return self.total_cost_usd / self.accepted

    @property
    def correction_calls(self) -> int:
        return sum(r.correction_calls for r in self.results)

    @property
    def structured_output_failures(self) -> int:
        return sum(1 for r in self.results if not r.structured_output_ok)

    @property
    def fact_failures(self) -> int:
        return sum(1 for r in self.results if not r.facts_ok)

    @property
    def completeness_failures(self) -> int:
        return sum(1 for r in self.results if r.completeness_ok is False)

    @property
    def letter_budget_failures(self) -> int:
        return sum(
            1 for r in self.results
            if r.letter_within_budget is False
        )

    @property
    def is_measured(self) -> bool:
        """Whether this score rests on real runs rather than on a projection."""
        return bool(self.results)


def rank(scores: list, *, by: str = "cost_per_accepted") -> list:
    """Order models for presentation.

    The default is **cost per accepted result**, ascending, which is the owner's
    stated basis. Models that accepted nothing sort last regardless of price, because
    a model that produces no accepted result is not a cheap option -- it is not an
    option.
    """
    def key(score: ModelScore):
        value = getattr(score, by)
        # None (nothing accepted) sorts after every real figure.
        return (value is None, value if value is not None else float("inf"))

    return sorted(scores, key=key)


def summarise(scores: list) -> str:
    """A table ready to paste into a decision record."""
    header = (
        f"{'model':34} {'acc':>5} {'cost':>9} {'/attempt':>10} {'/ACCEPTED':>11} "
        f"{'corr':>5} {'schema':>7}"
    )
    lines = [header, "-" * len(header)]
    for score in rank(scores):
        per_accepted = score.cost_per_accepted
        lines.append(
            f"{score.model_id[:34]:34} "
            f"{score.accepted}/{score.attempted:<3} "
            f"${score.total_cost_usd:8.4f} "
            f"${score.cost_per_attempt:9.5f} "
            f"{('$' + format(per_accepted, '.5f')) if per_accepted is not None else 'none accepted':>11} "
            f"{score.correction_calls:5} "
            f"{score.structured_output_failures:7}"
        )
    return "\n".join(lines)
