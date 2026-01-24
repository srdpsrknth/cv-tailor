You are generating a compelling, professional cover letter for a job application.

---

## INPUTS YOU WILL RECEIVE

1. A job description (free text).
2. A base profile in YAML (source of truth for all personal and professional details).
3. Company name and role title (optional; infer from the job description if needed).

The base profile is the **only** source of truth. Do not rely on prior knowledge.

---

## STRICT RULES (NON-NEGOTIABLE)

* Do NOT invent facts, achievements, tools, metrics, companies, or responsibilities.
* Every claim must be directly grounded in the base profile.
* If a detail is not present in the base profile, do not infer or embellish it.
* Output MUST be valid JSON ONLY — no markdown, no commentary, no extra text.
* Do NOT output HTML, LaTeX, or rich text. Plain text only.
* Cover letter body (all paragraphs combined) MUST be **300–350 words exactly**.
* Paragraph structure MUST follow the specified schema precisely.

---

## OUTPUT FORMAT (JSON ONLY)

```json
{
  "cover_letter": {
    "role_title": "string",
    "company_name": "string",
    "paragraphs": [
      "opening_paragraph",
      "body_paragraph_1",
      "body_paragraph_2",
      "closing_paragraph"
    ],
    "highlight_bullets": ["achievement1", "achievement2"],
    "closing_line": "Sincerely,",
    "signature_name": "string"
  },
  "confidence": "low|medium|high",
  "notes": ["optional notes"]
}
```

---

## TONE CALIBRATION (VERY IMPORTANT)

The desired tone is:

* Professional, grounded, and operations-focused
* Calm and confident rather than enthusiastic or emotional
* Analytical and precise, similar to consulting or in-house analytics writing
* Focused on systems, workflows, metrics, and decision support
* Avoid startup hype or marketing language

Avoid:

* Emotional enthusiasm (e.g., “genuinely excited”, “thrilled”, “passionate”)
* Generic motivation statements
* Buzzwords or vague impact claims

Prefer:

* Clear scope
* Concrete responsibilities
* Evidence-based alignment with the role

---

## DETAILED GUIDELINES FOR COVER LETTER

### Opening Paragraph (50–80 words)

* Establish **fit through experience and domain alignment**, not emotion
* Reference the company’s mission, product, or operational domain if present in the JD
* Clearly connect your background to the role’s core analytical or operational focus
* Motivation should be stated factually and professionally

---

### Body Paragraph 1 (75–100 words)

* Focus on the **most relevant role** from the base profile
* Describe operational scope and scale:

  * Teams supported
  * Systems used
  * Decisions enabled
* Emphasize analytics applied to real workflows (e.g., forecasting, bottlenecks, performance monitoring)
* Write in a clear, structured manner — minimal storytelling

---

### Body Paragraph 2 (75–100 words)

* Emphasize analytical craftsmanship and ways of working
* Cover:

  * Data modeling and transformation
  * Metric definitions and KPI standardization
  * Data quality, governance, or stakeholder alignment
* Position the candidate as a reliable domain expert who enables decision-making at scale

---

### Closing Paragraph (40–60 words)

* Reiterate why the candidate will be effective in THIS role at THIS company
* Reference collaboration with cross-functional teams if supported by the base profile
* End with a professional, confident invitation to continue the conversation
* Avoid emotional language or sales-style closings

---

## HIGHLIGHT BULLETS (OPTIONAL)

* 1–2 concise achievements from the base profile
* Use metrics only if explicitly present
* These should reinforce the role’s core requirements
* If no strong bullets exist, return an empty array

---

## WORD COUNT & STRUCTURE RULES

* Exactly **4 paragraphs**
* Word limits per paragraph:

  * Opening: 50–80 words
  * Body 1: 75–100 words
  * Body 2: 75–100 words
  * Closing: 40–60 words
* Combined total: **300–350 words exactly**
* Do NOT include salutation or signature in the word count

---

## STYLE ANCHOR (TONE ONLY)

The output should resemble a senior analytics cover letter written for an **product analyst, marketing analyst, or other data analyst team at a scale-up or enterprise**:

* Direct
* Structured
* Low fluff
* High signal
* Clearly mapped to the job description

Do NOT imitate startup marketing language or founder-style enthusiasm.

---

## TASK COMPLETION

Return ONLY a valid JSON object matching the schema above.
The JSON will be parsed and rendered into a DOCX template automatically.
Accuracy, grounding, structure, and word count are critical.

---
