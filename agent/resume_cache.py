"""Helpers for Gemini explicit context caching of the candidate resume."""

from google.genai import types

# Included in every resume cache so scoring requests can reference one stable
# resume block. Also helps smaller resumes meet Gemini's minimum cache size.
RESUME_EVALUATION_CONTEXT = """
## Resume evaluation context

The candidate resume above is the authoritative source for:
- Years and level of experience (intern, new grad, junior, mid, senior, staff)
- Technical skills, languages, frameworks, and tools
- Education, certifications, and notable projects
- Prior employers, domains, and role progression

When scoring jobs against this resume:
- Penalize clear seniority mismatches (e.g., principal role vs new grad)
- Weight directly relevant skills and stack overlap heavily
- Treat location as a soft factor unless the job explicitly requires on-site relocation
- Prefer honest scores: 0 = no realistic chance, 25 = stretch, 50 = possible,
  75 = good fit, 100 = overqualified

All subsequent requests in this session will ask you to score specific job postings
against this cached resume. Use only the resume and the job details provided in
each request.
""".strip()

CACHED_RESUME_SYSTEM_INSTRUCTION = (
    "You are a resume-to-job fit evaluator. The candidate resume is provided in cached "
    "context. Score each job honestly using this guide: 0 = no realistic chance, "
    "25 = weak stretch, 50 = possible fit, 75 = good fit, 100 = overqualified. "
    "Follow each request about whether to use title/metadata only or full job descriptions."
)


def build_resume_cache_contents(resume_text: str) -> list[types.Content]:
    cached_body = (
        f"Candidate resume:\n{resume_text}\n\n{RESUME_EVALUATION_CONTEXT}"
    )
    return [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=cached_body)],
        )
    ]
