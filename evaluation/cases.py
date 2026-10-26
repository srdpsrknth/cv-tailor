"""The evaluation cases, and the budget arithmetic that guards them.

The cases are the **synthetic** profiles and **anonymised** postings already in
``tests/fixtures/``. Nothing here reads the private store, so a live run cannot send
a real candidate's profile to a third party -- the constraint that makes an opt-in
paid suite acceptable at all.

**The budget is computed before anything is sent.** That ordering is the whole
point: a cap that is only checked while spending has already failed, because the
money is gone. :func:`project_cost` therefore models the worst realistic call count
per case -- not the happy path -- because a model that needs its correction loop is
exactly the model this suite is meant to catch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

#: Token shape of one application run, from ASSESSMENT §5 (measured against the
#: recorded fixture). A CV call is ≈6,438 input, a letter ≈5,265, and the outputs
#: ≈1,350 / 622. These are the numbers the projection is built from.
CV_INPUT_TOKENS = 6_438
CL_INPUT_TOKENS = 5_265
CV_OUTPUT_TOKENS = 1_350
CL_OUTPUT_TOKENS = 622
RETRY_INPUT_TOKENS = 740

#: Call counts per outcome, from the frozen baseline. Projection uses the
#: **max-successful** and **worst** figures rather than the minimum, so the estimate
#: is an upper bound: a run that comes in under budget is good news, and a run that
#: needs correction is already paid for.
CALLS_TYPICAL = 3
CALLS_MAX_SUCCESSFUL = 5
CALLS_WORST = 12


@dataclass(frozen=True)
class EvaluationCase:
    """One profile-plus-posting pair to generate against.

    ``profile_fixture`` and ``posting_fixture`` name files under ``tests/fixtures/``.
    A case that named anything else would be a bug, so :func:`fixture_path` confines
    resolution to that directory.

    ``company_name`` and ``role_title`` come from the **posting itself**, not from the
    case name, and that distinction is a correctness fix rather than tidiness. The
    letter prompt is told who the employer is and what the role is, and passing the case
    identifier instead produced cover letters addressed to a company called
    ``analyst_lumen`` for a position called ``Evaluation``. The document still passed
    every gate -- word count, facts, page count -- because no check looks at the
    salutation. Only a human reading the letter can see it, which is precisely the
    judgement the owner is asked to make, so the harness must not hand them a document
    whose heading is nonsense.
    """

    name: str
    profile_fixture: str
    posting_fixture: str
    #: What this case is here to exercise, in one line. Kept so a result table is
    #: readable without cross-referencing the fixtures.
    focus: str
    #: The employer named in the posting, used as the letter's addressee.
    company_name: str
    #: The role named in the posting.
    role_title: str


#: The case set. Three cases, deliberately: enough to expose a model that only works
#: on one kind of posting, few enough that the budget stays small. Each targets a
#: different failure mode the acceptance bar names. Every fixture is synthetic; see
#: ``tests/fixtures/README.md`` and ``tests/test_privacy_boundary.py``.
CASES: tuple[EvaluationCase, ...] = (
    EvaluationCase(
        name="analyst_nordwind",
        profile_fixture="profiles/synthetic_analyst.yaml",
        posting_fixture="job_descriptions/nordwind_analytics_engineer.txt",
        focus="the baseline case; the recorded transcript the offline suite uses",
        company_name="Nordwind Analytics GmbH",
        role_title="Analytical Engineer",
    ),
    EvaluationCase(
        name="analyst_lumen",
        profile_fixture="profiles/synthetic_analyst.yaml",
        posting_fixture="job_descriptions/lumen_growth_analyst.txt",
        focus="a second posting for the same profile, to catch overfitting to one JD",
        company_name="Lumen Consumer BV",
        role_title="Growth Analyst",
    ),
    EvaluationCase(
        name="marketer_harbor",
        profile_fixture="profiles/synthetic_marketer.yaml",
        posting_fixture="job_descriptions/harbor_marketing_data_analyst.txt",
        focus="a different profile in a different field, against a marketing posting",
        company_name="Harbor Retail Group",
        role_title="Marketing Data Analyst",
    ),
)


def fixtures_root() -> Path:
    """``tests/fixtures/``, addressed from this file so any worktree works."""
    return Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def fixture_path(relative: str) -> Path:
    """Resolve a fixture path, refusing to escape ``tests/fixtures/``.

    The confinement is not ceremony: this suite sends whatever it loads to a
    third-party API, so a path that could reach the private store would be a way to
    leak a real profile into a paid call.
    """
    root = fixtures_root().resolve()
    candidate = (root / relative).resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError(
            f"{relative!r} resolves outside tests/fixtures/, which is the only place "
            "this suite may read from."
        )
    if not candidate.exists():
        raise FileNotFoundError(f"fixture not found: {relative} (in {root})")
    return candidate


def projection_calls(case_count: int, *, pessimistic: bool = True) -> int:
    """How many calls to budget for ``case_count`` cases.

    Pessimistic by default: the point of a cap is to survive the bad case, and the
    bad case is the model that fails validation and retries.
    """
    per_case = CALLS_WORST if pessimistic else CALLS_MAX_SUCCESSFUL
    return per_case * case_count


def project_cost(
    input_per_1m: float,
    output_per_1m: float,
    case_count: int,
    *,
    pessimistic: bool = True,
) -> float:
    """Upper-bound USD for running ``case_count`` cases on one model.

    Per call this assumes the largest input the pipeline sends (a CV call) and the
    largest output (a CV draft), so the figure is an over-estimate rather than a
    flattering one. An over-estimate that causes a run to be refused is a safe
    failure; an under-estimate that causes an overrun is not.
    """
    calls = projection_calls(case_count, pessimistic=pessimistic)
    per_call = (
        (max(CV_INPUT_TOKENS, CL_INPUT_TOKENS) / 1_000_000) * input_per_1m
        + (max(CV_OUTPUT_TOKENS, CL_OUTPUT_TOKENS) / 1_000_000) * output_per_1m
    )
    return calls * per_call


@dataclass
class BudgetPlan:
    """A plan for a run, priced before anything is sent.

    :attr:`total_usd` is the projection across every model that would be tried.
    :meth:`exceeds` is what the runner consults, and it is asked **before** the first
    request.
    """

    per_model_usd: dict = field(default_factory=dict)
    cap_usd: float = 0.0

    @property
    def total_usd(self) -> float:
        return sum(self.per_model_usd.values())

    def exceeds(self, cap_usd: Optional[float] = None) -> bool:
        """Whether this plan is over budget. A missing cap is a refusal, not a pass.

        Defaulting an absent cap to "unlimited" is the failure this guards: an
        evaluation would then spend whatever it liked because nobody set a number.
        """
        cap = self.cap_usd if cap_usd is None else cap_usd
        if cap is None:
            return True
        return self.total_usd > cap

    def describe(self) -> str:
        """A table-ready summary, so the owner can approve a plan by reading it."""
        calls = projection_calls(len(CASES))
        lines = [
            f"Projected cost (upper bound: {len(CASES)} cases x "
            f"{calls // len(CASES)} calls = {calls} calls per model):",
        ]
        for model, cost in sorted(self.per_model_usd.items(), key=lambda kv: kv[1]):
            lines.append(f"  {model:42} ${cost:.4f}")
        lines.append(f"  {'TOTAL':42} ${self.total_usd:.4f}")
        lines.append(f"  {'CAP':42} ${self.cap_usd:.4f}")
        verdict = "OVER BUDGET -- refused" if self.exceeds() else "within budget"
        lines.append(f"  {verdict}")
        return "\n".join(lines)
