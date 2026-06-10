import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field

from agent.gemini_client import GeminiClient
from config import SearchConfig
from fetchers.registry import FetcherRegistry
from models.job import JobListing, ParsedJob

logger = logging.getLogger(__name__)

TITLE_BATCH_SIZE = 30
DEEP_BATCH_SIZE = 5

TITLE_SYSTEM_INLINE = (
    "You are a resume-to-job fit evaluator. Score how well a candidate's resume "
    "matches each job based on title and metadata only (no full description yet). "
    "Scoring guide: 0 = no realistic chance, 25 = weak stretch, 50 = possible fit, "
    "75 = good fit, 100 = overqualified. Be honest about seniority mismatches."
)

DEEP_SYSTEM_INLINE = (
    "You are a resume-to-job fit evaluator. Score how well a candidate's resume "
    "matches each job using the full job description. "
    "Scoring guide: 0 = no realistic chance, 25 = weak stretch, 50 = possible fit, "
    "75 = good fit, 100 = overqualified. Consider required skills, experience years, "
    "and responsibilities against the resume."
)


class TitleQualifyEntry(BaseModel):
    apply_url: str
    qualify_score: int = Field(ge=0, le=100)
    rationale: str


class TitleQualifyBatch(BaseModel):
    results: list[TitleQualifyEntry] = Field(default_factory=list)


class DeepQualifyEntry(BaseModel):
    apply_url: str
    qualify_score: int = Field(ge=0, le=100)
    rationale: str
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class DeepQualifyBatch(BaseModel):
    results: list[DeepQualifyEntry] = Field(default_factory=list)


@dataclass
class ResumeScoreStats:
    title_scored: int = 0
    full_scored: int = 0
    resume_cache_used: bool = False


class ResumeScorer:
    def __init__(self, gemini: GeminiClient, fetchers: FetcherRegistry):
        self._gemini = gemini
        self._fetchers = fetchers

    def score_jobs(
        self,
        resume_text: str,
        parsed_jobs: list[ParsedJob],
        config: SearchConfig,
    ) -> tuple[list[JobListing], ResumeScoreStats]:
        if not parsed_jobs:
            return [], ResumeScoreStats()

        stats = ResumeScoreStats(title_scored=len(parsed_jobs))

        with self._gemini.resume_cache_session(resume_text) as resume_cache:
            stats.resume_cache_used = resume_cache is not None
            title_scores = self._score_titles(
                resume_text,
                parsed_jobs,
                resume_cache=resume_cache,
            )

            deep_candidates: list[ParsedJob] = []
            final_by_url: dict[str, JobListing] = {}

            for parsed in parsed_jobs:
                entry = title_scores.get(parsed.listing.apply_url)
                if not entry:
                    final_by_url[parsed.listing.apply_url] = parsed.listing
                    continue

                listing = parsed.listing.model_copy(
                    update={
                        "qualify_score": entry.qualify_score,
                        "qualify_rationale": entry.rationale,
                        "qualify_scored_with": "title",
                    }
                )

                if entry.qualify_score > config.resume_deep_threshold:
                    deep_candidates.append(
                        ParsedJob(
                            listing=listing,
                            raw=parsed.raw,
                            ats_type=parsed.ats_type,
                            board_token=parsed.board_token,
                        )
                    )
                else:
                    final_by_url[parsed.listing.apply_url] = listing

            deep_results = self._score_deep(
                resume_text,
                deep_candidates,
                resume_cache=resume_cache,
            )
            stats.full_scored = len(deep_results)

            for parsed in deep_candidates:
                entry = deep_results.get(parsed.listing.apply_url)
                if entry:
                    final_by_url[parsed.listing.apply_url] = parsed.listing.model_copy(
                        update={
                            "qualify_score": entry.qualify_score,
                            "qualify_rationale": entry.rationale,
                            "qualify_scored_with": "full",
                        }
                    )
                else:
                    final_by_url[parsed.listing.apply_url] = parsed.listing

        listings = [
            final_by_url[p.listing.apply_url]
            for p in parsed_jobs
            if p.listing.apply_url in final_by_url
        ]

        return listings, stats

    def _score_titles(
        self,
        resume_text: str,
        parsed_jobs: list[ParsedJob],
        *,
        resume_cache: str | None,
    ) -> dict[str, TitleQualifyEntry]:
        scores: dict[str, TitleQualifyEntry] = {}

        for i in range(0, len(parsed_jobs), TITLE_BATCH_SIZE):
            batch = parsed_jobs[i : i + TITLE_BATCH_SIZE]
            job_summaries = [
                {
                    "title": p.listing.title,
                    "company": p.listing.company,
                    "location": p.listing.location,
                    "department": p.listing.department,
                    "apply_url": p.listing.apply_url,
                }
                for p in batch
            ]

            if resume_cache:
                prompt = (
                    "Use title and metadata only (no full job descriptions yet). "
                    "Be honest about seniority mismatches.\n\n"
                    f"Score each job below against the cached candidate resume:\n{job_summaries}\n\n"
                    "Return a qualify_score (0-100) and brief rationale for every job listed."
                )
                system_instruction = None
            else:
                prompt = (
                    f"Candidate resume:\n{resume_text}\n\n"
                    f"Score each job below (title/metadata only):\n{job_summaries}\n\n"
                    "Return a qualify_score (0-100) and brief rationale for every job listed."
                )
                system_instruction = TITLE_SYSTEM_INLINE

            try:
                result = self._gemini.generate_structured(
                    prompt=prompt,
                    schema=TitleQualifyBatch,
                    system_instruction=system_instruction,
                    cached_content=resume_cache,
                )
                for entry in result.results:
                    scores[entry.apply_url] = entry
            except Exception as exc:
                logger.warning("Title-only resume scoring failed for batch: %s", exc)

        return scores

    def _score_deep(
        self,
        resume_text: str,
        candidates: list[ParsedJob],
        *,
        resume_cache: str | None,
    ) -> dict[str, DeepQualifyEntry]:
        scores: dict[str, DeepQualifyEntry] = {}

        for i in range(0, len(candidates), DEEP_BATCH_SIZE):
            batch = candidates[i : i + DEEP_BATCH_SIZE]
            job_details: list[dict] = []

            for parsed in batch:
                description = self._fetchers.fetch_description(
                    parsed.ats_type,
                    parsed.board_token,
                    parsed.raw,
                )
                if not description:
                    logger.warning(
                        "No description for %s @ %s — keeping title-only score",
                        parsed.listing.title,
                        parsed.listing.company,
                    )
                    continue

                job_details.append(
                    {
                        "title": parsed.listing.title,
                        "company": parsed.listing.company,
                        "location": parsed.listing.location,
                        "department": parsed.listing.department,
                        "apply_url": parsed.listing.apply_url,
                        "description": description,
                    }
                )

            if not job_details:
                continue

            if resume_cache:
                prompt = (
                    "Use the full job descriptions below. Consider required skills, "
                    "experience years, and responsibilities against the cached resume.\n\n"
                    f"Score each job:\n{job_details}\n\n"
                    "Return qualify_score (0-100), rationale, strengths, and gaps for every job."
                )
                system_instruction = None
            else:
                prompt = (
                    f"Candidate resume:\n{resume_text}\n\n"
                    f"Score each job using the full descriptions:\n{job_details}\n\n"
                    "Return qualify_score (0-100), rationale, strengths, and gaps for every job."
                )
                system_instruction = DEEP_SYSTEM_INLINE

            try:
                result = self._gemini.generate_structured(
                    prompt=prompt,
                    schema=DeepQualifyBatch,
                    system_instruction=system_instruction,
                    cached_content=resume_cache,
                )
                for entry in result.results:
                    scores[entry.apply_url] = entry
            except Exception as exc:
                logger.warning("Deep resume scoring failed for batch: %s", exc)

        return scores
