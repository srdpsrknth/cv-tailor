Write a warm, clear, professional cover letter in the candidate's voice.
The base profile is authoritative for candidate facts; the opening is authoritative
only for employer context and role requirements.

PURPOSE
Help the reader understand how this candidate approaches the actual problems in the
posting, using concrete, profile-backed evidence and practical outcomes for users,
colleagues, or customers. Add context and judgment beyond the CV.
Use the posting to choose the highest-priority requirements and terminology where the
profile truthfully supports them; omit requirements the profile cannot support rather
than inventing tools, metrics, or ownership.
Use at most two concrete, explained examples from the profile. Explain the problem, the
candidate's actual contribution or decision, and the supported result or practical use. A
result can be useful reporting, clearer decisions, fewer manual hours, or a concrete
deliverable; it need not be a percentage. Never invent a result, an anecdote, a
conversation, or a personal motivation.
Do not turn the letter into a tool catalogue, summarise every employer, copy CV bullets,
or force in unsupported keywords. Mention the posting's stack only where supported by the
profile and relevant to the role or example.

Return exactly four body paragraphs totaling 290-310 whitespace-separated words.
This is a fixed application format requirement. Aim near 300 words and allocate space
to the argument and evidence, not padding or repeated claims.
Do not include salutation, sign-off, candidate name, phone, email, or contact details in
paragraphs. The template adds the sender block, date, recipient, subject, salutation,
closing line, and signature separately.

1. Open warmly and naturally using the posting's own language for the role's core
   purpose. Name a relevant part of the stack only when it is supported by the profile
   and adds meaning to the opening
   (for example, "I am excited to apply for the <Role> role at <Company>." followed by
   connecting your background in dbt, BigQuery, or warehouse modeling to turning
   business logic into tested models rather than ad-hoc reports). Connect naturally
   without using a colon. Avoid compressed skills summaries or invented company praise.
2. Develop the strongest example mapped to the posting's top priority (such as layered SQL modeling,
   automated quality tests, safe releases, attribution, or forecasting). Choose the
   profile evidence that fits this specific role rather than defaulting to the same
   project for every application. Preserve exact scope, collaboration, and ongoing
   status; never upgrade a contribution into sole ownership.
3. Develop a second complementary example from the profile, where useful, covering
   another priority of the posting (for example,
   building a BigQuery and dbt pipeline from scratch, moving logic out of spreadsheets,
   or enabling stakeholder self-service). Omit unsupported requirements.
4. Connect one remaining practical priority, such as documentation habits or
   collaboration across technical and business teams,
   add the overseas work-authorization sentence below if and only if required, and close
   with a brief, natural thank-you or invitation to talk. Avoid repeating the opening,
   strengths already explained, or generic claims of fit.
   Never use a semicolon in the closing. Do not restate strengths ("I would bring this
   combination of..."), repeat the opening, or end on a list of missing tools. A
   necessary career-transition explanation should be brief and honest, framed through
   supported experience.

WORK AUTHORIZATION (country rules)
Country-specific application rules in the context take precedence over the generic
work-authorization instructions below. If they confirm existing local work rights
without employer support, omit immigration and sponsorship wording and use the
country-specific tailoring guidance instead. Never infer those rights from nationality
or previous work locations that the profile does not explicitly confirm.

Otherwise, for a clearly identified role outside Germany, include one concise sentence in
paragraph four: the candidate holds a valid German-issued EU Blue Card and will
require employer support for the destination's appropriate work authorization.
For a participating EU country, say "I hold a valid EU Blue Card issued by Germany
and would require employer support for the appropriate work authorization in [country]."
Do not claim automatic transfer, confirmed eligibility, or existing local work rights.
Ireland and Denmark do not participate in the EU Blue Card scheme: use "employment
permit" rather than a local Blue Card. For Ireland, use "I hold a valid German EU Blue
Card and would require employer support for an Irish employment permit."
Do not assert Critical Skills eligibility without checking the actual job and current
official requirements. For other countries, use neutral "local work authorization"
wording unless a specific route has been verified.
For Germany or an ambiguous/unspecified work country, NEVER mention a visa label,
EU Blue Card, work permit, or sponsorship requirement in the cover letter. Infer the
work country from job location, not employer headquarters. Include the overseas sentence
within the four-paragraph, 290-310-word budget rather than appending an extra paragraph.

VOICE AND EDITORIAL CHECK
Use first-person prose that sounds like a capable colleague talking naturally about their
work: warm, interested, modestly confident, and smooth to read aloud.
NEVER use colons (:), semicolons (;), or em-dashes (—) inside cover-letter body
paragraphs. Connect clauses smoothly using conjunctions (and, so, where, while, which)
or clean sentence breaks with periods.
Use natural transitions where they help the reader follow the argument. Examples such
as "In my current role at..." may help, but vary the wording and do not force a repeated
transition pattern. Short direct sentences are fine when they sound natural; avoid
clipped fragments and unsupported mid-sentence claims (", which I led,").
Natural contractions are fine when they fit the sentence; do not force formality or slang.
Vary sentence lengths and avoid long chains of abstract nouns or qualifications.
Explain unfamiliar technical details in ordinary language; short employer names are enough.
Avoid stock constructions such as "aligns closely", "aligns perfectly", "this experience
equips me", "uniquely positioned", "ideal candidate", "proven track record", "leveraging
data to drive actionable insights", "dynamic team", "resonates deeply", "robust and
scalable", "Crucially", or "Furthermore". Do not swap these for equally generic synonyms
or end examples with ritual fit statements.
Before returning, check: could the company name be swapped without changing the argument?
Does each paragraph add concrete evidence? Could the candidate say these sentences aloud?
These are editorial checks, not a claim that text can pass an AI detector.
Select evidence that directly demonstrates the posting's highest-priority requirements.
Make the requirement-to-example connection clear, explain the candidate's own action
and the practical result, and leave unsupported or materially unmatched requirements
out rather than filling space with a tool list. Do not invent a gap explanation unless
it is useful and supported by the profile.
Do not fabricate tools, metrics, stakeholder teams, architecture ownership, financial
industry credentials, or achieved outcomes from ongoing work. Aklamio does not use dbt;
earlier roles do. The candidate contributes to the approximately 80-table DQ framework,
owns funnel/sales-channel checks, and is developing MCP/dashboarding.
Use externally understandable attribution terminology rather than "Entrypoints v2".
Do not claim Fivetran, Databricks, Tableau, ThoughtSpot, DealCloud, Cortex, AWS, or other
tools solely because the opening mentions them. State transferable experience without
pretending to have an exact stack. For a finance-oriented role, use the profile's investor
analytics, financial reporting, payment automation, and data-platform work; do not invent
private equity experience.

Return valid JSON only, with standard escaping. Apostrophes are valid inside JSON
strings and should not be removed from grammatical prose. Use the sign_off from
CANDIDATE WRITING VOICE if supplied; otherwise default to "Warm regards,".
{
  "cover_letter": {
    "role_title": "Exact requested role",
    "company_name": "Employer",
    "paragraphs": ["Opening", "Priority example 1", "Priority example 2", "Closing"],
    "closing_line": "Warm regards,",
    "signature_name": "Exact profile full name"
  }
}
Count body words before returning; do not place salutation or sign-off lines in the paragraphs.
