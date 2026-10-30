"""The curation skill file: the procedure an agent follows (Q9).

The skill is the **procedure** and the CLI is the **tool**. The whole point of that split
is that the valuable part of the first curation was not the commands -- it was the
judgement: which candidates to drop and why, that the acceptance bar must not vary, that
the owner's reading is required before a quality claim. That is instructions, not code,
and it is what this file is for.

These tests pin the properties that make it safe to follow. They are deliberately about
*content that could be dangerous if wrong* rather than about wording: a skill that told an
agent to run ``--live`` without asking, or to set ``verified="measured"`` from a table,
would be a mechanism for spending money and making unearned claims.

Nothing here is network-dependent. The file is read as text.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / ".agents" / "skills" / "cv-model-curation" / "SKILL.md"


@pytest.fixture(scope="module")
def skill_text() -> str:
    assert SKILL_PATH.is_file(), (
        f"the curation skill is missing at {SKILL_PATH}. It is the procedure half of "
        f"Q9's answer; the CLI alone does not say what order to do things in, or what "
        f"must not be done"
    )
    return SKILL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def skill_flat(skill_text: str) -> str:
    """The skill's text, lowercased with every run of whitespace collapsed to one space.

    Markdown is hard-wrapped, so a phrase an author wrote as one sentence is split across
    a newline in the file -- "a successful\\nre-curation". Asserting on the raw text would
    fail for a reason that has nothing to do with the content, and the tempting fix is to
    reword the prose to satisfy the test. Flattening first keeps the assertion about what
    the skill *says*.
    """
    return " ".join(skill_text.lower().split())


# --- it is a skill file the harness can load -----------------------------------------------

def test_the_skill_has_valid_frontmatter(skill_text):
    """A skill without a name and a description cannot be discovered or triggered."""
    assert skill_text.startswith("---\n"), "frontmatter must open the file"
    _, frontmatter, _ = skill_text.split("---", 2)

    assert "name: cv-model-curation" in frontmatter
    assert "description:" in frontmatter
    # The description is what an agent matches a request against, so it must name the
    # situations, not just the topic.
    description = frontmatter.split("description:", 1)[1].lower()
    assert "re-curate" in description or "refresh" in description


def test_the_skill_lives_beside_the_others():
    """``.agents/skills/<name>/SKILL.md`` -- the layout ``cv-tailor-application`` uses."""
    siblings = {p.parent.name for p in (SKILL_PATH.parents[1]).glob("*/SKILL.md")}
    assert "cv-tailor-application" in siblings
    assert "project-continuity" in siblings
    assert "cv-model-curation" in siblings


# --- the spend rules, which are the reason this file is dangerous if wrong ------------------

def test_it_requires_the_owners_yes_before_any_paid_run(skill_text):
    """**The rule that must never be softened.**

    ADR 0005 requires the method and a spending budget be agreed with the owner before any
    paid call. A skill that told an agent to just run the study would be a mechanism for
    spending money on the owner's behalf.
    """
    lowered = skill_text.lower()

    assert "never run `--live`" in lowered
    assert "explicit yes" in lowered or "explicit go-ahead" in lowered
    # And it must say the approval happens in the conversation, not in a document.
    assert "current conversation" in lowered or "in the current conversation" in lowered


def test_it_shows_the_projection_before_asking(skill_text):
    """The cap guards against an overrun, not against a wrong plan."""
    lowered = skill_text.lower()

    assert "projection" in lowered
    assert "dry run" in lowered


def test_it_says_the_cap_is_per_run_and_not_to_be_raised_unilaterally(skill_text):
    lowered = skill_text.lower()

    assert "per run" in lowered
    assert "do not raise it" in lowered or "owner's decision" in lowered


def test_it_does_not_instruct_an_agent_to_switch_the_default(skill_text):
    """**The Q6 decision, enforced.**

    Switching changes what every future application is generated with. The skill may
    recommend; it must not act. Asserted by requiring the explicit prohibition, because an
    omission would read as permission.
    """
    lowered = skill_text.lower()

    assert "never switch the default autonomously" in lowered
    # And the switch is still described as a thing a person does, so the file is not
    # simply silent about it.
    assert "owner's call" in lowered or "owner's decision" in lowered


def test_it_says_the_report_applies_nothing(skill_text):
    """Q2: the proposal is a diff for approval, never a replacement."""
    lowered = skill_text.lower()

    assert "never applies it" in lowered or "writes nothing" in lowered
    assert "separate" in lowered and "commit" in lowered


# --- the human judgement step ---------------------------------------------------------------

def test_it_states_that_the_human_verdict_is_required(skill_text):
    """Q7. The suite measures acceptance, cost and calls -- and no prose or rendering."""
    lowered = skill_text.lower()

    assert "verdict" in lowered
    assert "not advisory" in lowered or "enforced in" in lowered
    # The limit must be stated, not implied.
    assert "no prose" in lowered or "measures none" in lowered


def test_it_tells_the_agent_not_to_fill_in_the_verdicts(skill_text):
    """A verdict written by the agent would defeat the entire step."""
    lowered = skill_text.lower()

    assert "do not fill the verdicts in yourself" in lowered


def test_it_requires_a_measured_rationale_for_a_dialect(skill_text):
    """ADR 0016: a hint from the screen is ``assumed`` and is not a measurement."""
    lowered = skill_text.lower()

    assert "measured" in lowered and "rationale" in lowered
    assert "not a measurement" in lowered or "assumed" in lowered
    # The three measured family constraints are carried forward, so the next session does
    # not re-buy them at the price of a failed call each.
    assert "additionalproperties" in lowered
    assert "24 optional parameters" in lowered or "optional parameters" in lowered


# --- the fairness rules that make per-candidate tuning honest -------------------------------

def test_it_says_the_acceptance_bar_never_varies(skill_text):
    """ADR 0016's load-bearing property: only the *asking* may differ."""
    lowered = skill_text.lower()

    assert "acceptance bar is identical" in lowered
    assert "only the *asking* may vary" in lowered or "only the asking may vary" in lowered


def test_it_forbids_a_quality_claim_from_a_leaderboard(skill_text):
    """ADR 0005 and ADR 0014: no benchmark measures CV prose."""
    lowered = skill_text.lower()

    assert "leaderboard" in lowered
    assert "no benchmark measures cv prose" in lowered


def test_it_says_cost_is_per_accepted_result(skill_text):
    """The headline metric, and the one that makes a failing cheap model visible."""
    lowered = skill_text.lower()

    assert "per *accepted* result" in lowered or "per accepted result" in lowered
    assert "never per call" in lowered


# --- the operational traps this project has actually hit ------------------------------------

def test_it_warns_about_the_price_row(skill_text):
    """Without a row, ``price_for`` borrows the fallback and the ranking becomes fiction."""
    lowered = skill_text.lower()

    assert "price row" in lowered or "pricing.py" in lowered
    assert "fallback" in lowered


def test_it_warns_about_clearing_the_sandbox(skill_text):
    """A stale store puts a previous slate's documents in the reading packet.

    Measured: the 2026-10-30 store held six job folders per case from six different runs.
    """
    lowered = skill_text.lower()

    assert "clear the sandbox" in lowered
    assert "remove-item -recurse -force .tmp\\evaluation-store" in lowered


def test_it_carries_the_byte_level_house_rules(skill_text):
    """Both have bitten this project: a BOM makes a JSON file unparseable, and the Python
    subprocess cannot write most tracked paths in this worktree."""
    assert "UTF8Encoding" in skill_text
    assert "BOM" in skill_text or "bom" in skill_text.lower()


def test_it_protects_the_private_store(skill_text):
    """A live run must never send a real candidate's profile to a third party."""
    lowered = skill_text.lower()

    assert "tests/fixtures/" in skill_text
    assert "never point it at the private store" in lowered


def test_it_reminds_that_adrs_are_history(skill_text):
    lowered = skill_text.lower()
    assert "adrs are history" in lowered
    # Named in backticks in the file, so the assertion strips them and matches the
    # identifier itself.
    assert "geminiservice" in lowered.replace("`", "")


# --- the procedure is complete and ordered --------------------------------------------------

def test_it_lays_out_the_whole_procedure_in_order(skill_text):
    """An agent must be able to follow it end to end without inventing a step."""
    for step in ("detect", "screen", "reading packet", "proposal"):
        assert step in skill_text.lower(), step
    # The six numbered steps.
    for number in range(1, 7):
        assert f"## Step {number}" in skill_text, number


def test_it_names_the_commands_it_tells_the_agent_to_run(skill_text):
    """Every command in the file must be one that exists."""
    for verb in ("--detect", "--screen", "--report", "--packet", "--live", "--cap-usd"):
        assert verb in skill_text, verb


def test_it_says_a_no_change_result_is_a_success(skill_flat):
    """Otherwise an agent runs a study to confirm that nothing moved, and spends for it."""
    assert "no changes" in skill_flat
    assert "successful re-curation" in skill_flat
    assert "confirm that nothing moved" in skill_flat


def test_it_says_the_report_may_recommend_keeping_the_current_model(skill_text):
    """A common outcome, and it must not read as a failure to find anything."""
    lowered = skill_text.lower()

    assert "keep the current model" in lowered
    assert "real and common outcome" in lowered
