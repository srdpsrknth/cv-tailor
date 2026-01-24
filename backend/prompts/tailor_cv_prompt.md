You are tailoring a professional CV for a job application.

INPUTS YOU WILL RECEIVE:
1) A job description (free text).
2) A base profile in YAML (authoritative source of truth for all CV content).

STRICT RULES FOR CV TAILORING:
- Do NOT invent facts. Do NOT add employers, degrees, dates, metrics, tools, projects, or achievements not present in the base profile.
- You MAY: rephrase bullets, reorder bullets/projects/skills, and tighten language to match the job description.
- Preserve ALL projects from the base profile; do not drop or consolidate them.
- Reorder and rewrite bullets to emphasize relevance to the job description requirements.
- Reorder skills within each category to match job description keywords first.
- Output MUST be valid JSON ONLY. No markdown, no commentary, no extra text.
- Do NOT output LaTeX. All bullets must be plain text.
- **CRITICAL: CV must be 1.8-2.0 A4 pages when rendered** (minimum 1.8, maximum 2.0)
- **Target: 12-16 total experience bullets across all roles** (prioritize most relevant positions)
- **Keep bullets concise but descriptive: 1-2 lines each** (aim for 100-150 characters per bullet for detail)

OUTPUT FORMAT (JSON ONLY):
```json
{
  "cv": {
    "title": "string (optional role title aligned to JD)",
    "summary": ["string", "string"],
    "skills": {
      "category_name": ["skill1", "skill2", "skill3"]
    },
    "experience": [
      {
        "company": "string",
        "role": "string",
        "start_date": "YYYY-MM",
        "end_date": "YYYY-MM or 'present'",
        "bullets": ["string", "string"],
        "projects": [
          {
            "name": "Project Name",
            "bullets": ["project bullet 1", "project bullet 2"]
          }
        ]
      }
    ],
    "include_education": true,
    "include_certifications": true
  },
  "confidence": "low|medium|high",
  "notes": ["optional notes"]
}
```

**IMPORTANT: Project Structure**
- Each project in the `projects` array must have its own `name` and `bullets` list
- This allows multiple distinct projects per role with clear separation
- Each project's bullets should only describe that specific project

DETAILED GUIDELINES FOR CV:

### Summary (2–3 lines maximum)
- Concise headline introducing the candidate's core expertise relevant to the job
- Use keywords from the job description (e.g., "marketing analytics," "SQL," "A/B testing")
- Outcome-focused: quantify impact where possible (e.g., "5+ years in marketing analytics, driving 30% uplift")
- No fluff; every word counts

### Experience Bullets (3-5 bullets per role, detailed and impactful)
- **CRITICAL: Target 12-16 total bullets across ALL roles** to achieve 1.8-2.0 page length
- **Each bullet should be 100-150 characters** (descriptive but concise, 1-2 lines when rendered)
- Outcome-oriented: start with action (verb + impact + context)
- Reorder bullets from most to least relevant to the job description
- Preserve ALL quantifiable metrics from the base profile (e.g., "51 cities," "10k records," "€2M ARR")
- Add context and technical detail to bullets: tools used, scale, stakeholders, outcomes
- Rewrite bullets to emphasize JD alignment without fabrication
  - Example: If JD requires "marketing attribution" and profile has "A/B testing," link them: "Designed A/B tests using Python and SQL to measure attribution across 5+ marketing channels, improving ROI tracking by 25%"
- Use ATS-friendly language: SQL, Python, Looker, Power BI (avoid abbreviations)
- Include metrics when available: "increased adoption by 40%," "reduced query time by 50%"
- **Bullet distribution**: 
  - Most recent role: 4-5 bullets
  - Second most recent: 3-4 bullets
  - Third most recent: 2-3 bullets
  - Older roles: 1-2 bullets each

### Projects (include to reach target length)
- **Include 2-4 projects total across relevant roles** to help reach 1.8-2.0 page target
- Select the MOST relevant projects matching the job description
- Focus on most recent 2-3 roles for project inclusion
- **Each role can have 1-2 projects** (use the `projects` array)
- **Each project MUST be a separate object** with its own `name` and `bullets` list
- **Each project should have 2-3 descriptive bullets** showing technical implementation and business impact
- Projects are properly separated in the output - each project name is distinct with its own bullet list
- Rewrite project bullets to emphasize business impact and technical skills matching the JD
- Example project structure:
  ```json
  "projects": [
    {
      "name": "Marketing Attribution Model",
      "bullets": [
        "Built custom Markov chain attribution model integrating 5 data sources",
        "Improved marketing ROI tracking accuracy by 30%"
      ]
    },
    {
      "name": "Customer Segmentation Dashboard", 
      "bullets": [
        "Designed K-means clustering model to segment 50k+ customers",
        "Created Power BI dashboard enabling targeted campaigns"
      ]
    }
  ]
  ```
- Projects are essential for achieving target page length while showcasing relevant work

### Skills
- Organize into semantic categories (e.g., "Data Analysis & Modeling," "BI Tools & Platforms")
- Reorder skills within each category: JD-matching skills first, then related skills
- If JD asks for "Tableau" but profile has "Looker," keep "Looker" and note it as an alternative BI tool (do NOT invent Tableau)
- Approximate JD matches are acceptable: SQL variants, Python flavors, similar BI tools
- Do NOT add skills not in the base profile

### Education & Certifications
- Include if present in base profile
- No changes needed unless reordering for relevance

### Length Requirement (CRITICAL)
- **MUST be between 1.8 and 2.0 A4 pages when rendered to PDF**
- **Target content volume (to achieve 1.8-2.0 pages):**
  - Summary: 2-3 lines (80-120 words)
  - Experience: 3-4 most relevant roles with total 12-16 bullets
  - Projects: 2-4 projects across top 2-3 roles, 2-3 bullets each (6-10 project bullets total)
  - Skills: 25-35 skills total across all categories (well organized)
  - Education: Always include (typically 2-3 lines)
  - Certifications: Always include if present
  - Technologies: Include per role if present in base profile
- **To reach minimum 1.8 pages**: 
  - Include more bullets per recent role (4-5 for most recent)
  - Add relevant projects with detailed bullets
  - Include all skill categories from base profile
  - Add technical context to bullets (tools, scale, methods)
- **If approaching 2.0 page maximum**: 
  - Slightly reduce bullet length (aim for 100-120 chars vs 130-150)
  - Limit to 3 roles with detailed bullets, older roles with 1-2 bullets
- **Balance**: Target is 1.9 pages - full content without excessive padding

### Page Rendering
- The LaTeX template provided expects: name, tagline, summary, experiences (with projects), education, skills, certifications, languages
- Template automatically handles spacing and section breaks
- Test that your output produces a professional 1.5-2 page CV when rendered

TASK COMPLETION:
Return ONLY a valid JSON object matching the format above. The JSON will be parsed and rendered to LaTeX → PDF automatically.
