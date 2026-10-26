"""The live evaluation suite: opt-in, budget-capped, and never in CI.

ADR 0005 requires an evaluation over synthetic profiles and anonymised postings
comparing **accuracy, completeness, relevance, writing quality, structured-output
success, unnecessary claims, correction attempts and total cost per *accepted*
result**. This package is it.

Four properties are deliberate, and each exists because of a way this could go
wrong:

1. **Offline by default.** :func:`dry_run` makes no call. A live run requires the
   explicit ``live=True`` *and* a present key; there is no path where a missing flag
   falls through to a paid request.
2. **Budget-capped, and it fails closed.** A plan whose *projection* exceeds the cap
   is refused before the first call, and a run halts when spend crosses the cap. A
   cap that fails open is worse than no cap, because it looks like one.
3. **Out of CI.** The suite is not named ``test_*``, so pytest does not collect it,
   and the tests assert that. Its paid path cannot run in a test job by accident.
4. **Cost is per accepted result.** The headline metric is not cost per call. A cheap
   model that fails the factual gate and burns three correction calls is not cheap,
   and only the accepted-result denominator shows that.

The suite reads only the synthetic fixtures in ``tests/fixtures/`` -- never the
private store -- so it can never send a real candidate's data to a third party.
"""
