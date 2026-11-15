# LinkedIn MCP: signed-in browser access

**Reviewed:** 2026-11-15. Source inspected at
[`e9b47a48634200a836571b4e7c02444844038229`](https://github.com/stickerdaniel/linkedin-mcp-server/tree/e9b47a48634200a836571b4e7c02444844038229).
Read-only source review; no installation, account login or live LinkedIn query.

The earlier Phase 4 research assessed public endpoints under ADR 0008. This server
demonstrates a different technical route: a signed-in browser exposed over MCP.
The exclusion of LinkedIn from the shipped connector set is not evidence that job
retrieval is technically impossible.

## How postings are retrieved

1. The server uses Patchright Chromium with a persistent LinkedIn login. Its README
   describes manual browser login or importing a local browser's signed-in session.
2. `search_jobs(keywords, location, ...)` navigates LinkedIn's rendered job-search
   pages, scrolls/paginates, and returns raw search text, job IDs and paging metadata.
   The default is three pages; the tool accepts one to ten.
3. `get_job_details(job_id)` opens the posting and returns its URL and captured
   posting text, with errors for missing/incomplete descriptions. The tool expects
   its calling agent to interpret the text; it does not return CV Tailor's normalized
   `Job` schema.
4. `get_job_apply_url` distinguishes employer links, Easy Apply, applied/closed and
   unknown states. Job reading does not require application submission.

The source explicitly excludes direct Voyager/private API calls. Its mechanism is
rendered-page navigation and text extraction. Search can be partial (timeout,
repeated results, rate limiting); the redesigned LinkedIn search can also discard
location or other filters, which is reported in `section_errors`.

## Implication for CV Tailor

An optional MCP adapter could call search, fetch details for selected IDs, normalize
the captured fields into `Job`, and retain the LinkedIn URL/ID and field provenance.
It would need to surface dropped filters and partial results rather than presenting
them as complete, geographically filtered search results. Credentials/session files
belong outside the public repository.

This is a feasible integration direction inferred from the source, not a completed
connector or evidence of official LinkedIn partner authorization. The repository's
source policy remains unchanged by this review. No new dependency was installed.

## Primary sources

- [README and session setup](https://github.com/stickerdaniel/linkedin-mcp-server/blob/e9b47a48634200a836571b4e7c02444844038229/README.md)
- [MCP job tools](https://github.com/stickerdaniel/linkedin-mcp-server/blob/e9b47a48634200a836571b4e7c02444844038229/linkedin_mcp_server/tools/job.py)
- [Search and posting reader](https://github.com/stickerdaniel/linkedin-mcp-server/blob/e9b47a48634200a836571b4e7c02444844038229/linkedin_mcp_server/linkedin/jobs.py)
- [Rendered-page decision](https://github.com/stickerdaniel/linkedin-mcp-server/blob/e9b47a48634200a836571b4e7c02444844038229/docs/decisions/2026-09-16-rendered-page.md)
