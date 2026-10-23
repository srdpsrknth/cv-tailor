# Test fixtures

**Every value in this directory is synthetic.** No real candidate data, no real job
postings, no recorded real API traffic. Names, employers, dates, metrics and contact
details are invented for testing and must stay that way.

These fixtures exist so the whole test suite runs **deterministically and offline** — no
paid API calls, no network. See `docs/TESTING.md`.

## Layout

```
tests/fixtures/
  profiles/
    synthetic_analyst.yaml        profile A — "Alex Sample", analytics engineer
    synthetic_marketer.yaml       profile B — "Robin Example", growth marketer
    invalid/
      unknown_key.yaml            extra="forbid" violation
      missing_identity.yaml       required-field violation
      malformed.yaml              not a YAML mapping
      broken_syntax.yaml          unparseable YAML
  job_descriptions/
    nordwind_analytics_engineer.txt     anonymised posting (Berlin)
    lumen_growth_analyst.txt            anonymised posting (Amsterdam)
    harbor_marketing_data_analyst.txt   anonymised posting (Dublin)
  llm_responses/
    analyst_nordwind/             recorded provider responses for profile A
    marketer_lumen/               recorded provider responses for profile B
  content/
    valid_content.json            minimal `content.json` accepted by the renderers
    invalid_content.json          deliberately malformed (for failure-path tests)
```

## Why two profiles

`ASSESSMENT.md` §4 lists *cross-profile contamination* as an untested gap and
[ADR 0003](../../../docs/DECISIONS/0003-profile-identity.md) threads an explicit
`profile_id` through every layer. A second synthetic profile makes it possible to assert
that generating for one profile cannot leak another profile's facts into prompts or output.

The two profiles deliberately differ in shape as well as content:

| | `synthetic_analyst` | `synthetic_marketer` |
|---|---|---|
| Employers | 3, incl. one with **no bullets** | 2, all with bullets |
| Selected projects | present on two employers | none |
| `visa_status` | present (work-authorization paths) | absent |
| `certifications` | present | empty |
| `work_country` paths | Germany / Ireland | Netherlands |

## Recorded LLM responses

`llm_responses/<session>/<step>.json` are hand-written, schema-valid documents in the shape
the provider is expected to return. They are wrapped `{"cv": …}` / `{"cover_letter": …}`
objects, sometimes inside a Markdown code fence, which is exactly what the parser must
tolerate.

`responses.json` in each session directory maps a step name to the file that holds it, so
tests read the manifest and never hardcode file wiring.
