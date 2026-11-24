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

1. Open naturally with the role’s purpose and the candidate’s supported interest.
2. Explain a relevant profile-backed example, preserving scope and collaboration.
3. Explain a complementary supported example where useful.
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

Discuss work authorization or employer support only when the selected profile and applicable country policy establish those facts. Do not infer status, requirements, or eligibility. Follow any explicit country-specific rules.

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
Do not fabricate tools, metrics, ownership, outcomes, or completed work. Use only evidence from the profile.

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
