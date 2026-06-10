import logging
import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from agent.gemini_client import GeminiClient
from config import SearchConfig
from models.job import JobListing, RawJob

logger = logging.getLogger(__name__)

ROLE_KEYWORDS = re.compile(
    r"\b(engineer|developer|software|backend|frontend|full.?stack|devops|sre|data|ml|ai)\b",
    re.IGNORECASE,
)

EXPERIENCE_PATTERNS: dict[str, list[str]] = {
    "entry": ["entry", "junior", "intern", "graduate", "new grad", "associate", "0-2", "0-1"],
    "mid": ["mid", "intermediate", "ii", "2-4", "3-5", "2-5"],
    "senior": ["senior", "sr.", "sr ", "iii", "iv", "5+", "5-8", "6+"],
    "lead": ["lead", "staff", "principal", "architect", "director", "head of"],
}


class ScoredJob(BaseModel):
    title: str
    company: str
    location: str | None = None
    department: str | None = None
    apply_url: str
    ats: str
    source_company_url: str
    match_score: float = Field(ge=0.0, le=1.0)


class ScoredJobList(BaseModel):
    jobs: list[ScoredJob] = Field(default_factory=list)


class JobParser:
    def __init__(self, gemini: GeminiClient):
        self._gemini = gemini

    def parse_and_filter(
        self,
        config: SearchConfig,
        company_name: str,
        ats_type: str,
        careers_url: str,
        raw_jobs: list[RawJob],
    ) -> list[tuple[JobListing, RawJob]]:
        if not raw_jobs:
            return []

        eligible_jobs = [job for job in raw_jobs if self._posted_within_window(config, job)]
        if not eligible_jobs:
            return []

        fast_path_jobs = [
            job
            for job in eligible_jobs
            if self._fast_path_eligible(config, job)
        ]

        if len(fast_path_jobs) == len(eligible_jobs):
            return [
                (self._to_listing(job, company_name, ats_type, careers_url, score=0.85), job)
                for job in fast_path_jobs
            ]

        borderline_jobs = [job for job in eligible_jobs if job not in fast_path_jobs]
        llm_pairs: list[tuple[JobListing, RawJob]] = []
        batch_size = 40
        for i in range(0, len(borderline_jobs), batch_size):
            batch = borderline_jobs[i : i + batch_size]
            llm_pairs.extend(
                self._score_with_llm(config, company_name, ats_type, careers_url, batch)
            )

        pairs = [
            (self._to_listing(job, company_name, ats_type, careers_url, score=0.85), job)
            for job in fast_path_jobs
        ]
        pairs.extend(llm_pairs)
        return pairs

    def _posted_within_window(self, config: SearchConfig, job: RawJob) -> bool:
        if config.posted_within_days is None:
            return True
        if job.posted_at is None:
            return True

        cutoff = datetime.now(timezone.utc) - timedelta(days=config.posted_within_days)
        posted = job.posted_at
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        return posted >= cutoff

    def _fast_path_eligible(self, config: SearchConfig, job: RawJob) -> bool:
        if not job.title or not job.apply_url:
            return False

        title_matches = self._title_matches_role(config.role, job.title)
        location_matches = self._location_matches(config, job.location)
        experience_matches = self._experience_matches(config.experience, job.title)

        return title_matches and location_matches and experience_matches

    def _title_matches_role(self, role: str, title: str) -> bool:
        role_lower = role.lower()
        title_lower = title.lower()

        role_tokens = [t for t in re.split(r"\W+", role_lower) if len(t) > 2]
        if role_tokens and any(token in title_lower for token in role_tokens):
            return True

        return bool(ROLE_KEYWORDS.search(title_lower))

    def _experience_matches(self, experience: str, title: str) -> bool:
        if not experience or experience.lower() in {"any", "all"}:
            return True

        title_lower = title.lower()
        target_lower = experience.lower()

        target_tier = self._experience_tier(target_lower)
        title_tier = self._experience_tier(title_lower)

        if target_tier and title_tier:
            tier_order = ["entry", "mid", "senior", "lead"]
            target_idx = tier_order.index(target_tier)
            title_idx = tier_order.index(title_tier)
            return abs(title_idx - target_idx) <= 1

        target_tokens = [t for t in re.split(r"\W+", target_lower) if len(t) > 1]
        if target_tokens and any(token in title_lower for token in target_tokens):
            return True

        year_match = re.search(r"(\d+)\s*[-+]?\s*(?:years?|yrs?)?", target_lower)
        if year_match:
            years = year_match.group(1)
            if years in title_lower:
                return True

        return True

    def _experience_tier(self, text: str) -> str | None:
        for tier, keywords in EXPERIENCE_PATTERNS.items():
            if any(keyword in text for keyword in keywords):
                return tier
        return None

    def _location_matches(self, config: SearchConfig, location: str | None) -> bool:
        if not location:
            return config.include_remote

        location_lower = location.lower()
        target_lower = config.location.lower()

        if "remote" in location_lower and config.include_remote:
            return True

        target_parts = [p.strip() for p in re.split(r",|\s+", target_lower) if p.strip()]
        return any(part in location_lower for part in target_parts if len(part) > 2)

    def _score_with_llm(
        self,
        config: SearchConfig,
        company_name: str,
        ats_type: str,
        careers_url: str,
        raw_jobs: list[RawJob],
    ) -> list[tuple[JobListing, RawJob]]:
        if not raw_jobs:
            return []

        job_summaries = [
            {
                "title": job.title,
                "location": job.location,
                "department": job.department,
                "apply_url": job.apply_url,
                "posted_at": job.posted_at.isoformat() if job.posted_at else None,
            }
            for job in raw_jobs
        ]

        post_time_hint = (
            f"Posted within the last {config.posted_within_days} days"
            if config.posted_within_days is not None
            else "No posting date restriction"
        )
        experience_hint = config.experience or "any experience level"

        prompt = (
            f"Filter and score these job postings for relevance.\n\n"
            f"Target role: {config.role}\n"
            f"Target location: {config.location}\n"
            f"Target experience: {experience_hint}\n"
            f"Posting window: {post_time_hint}\n"
            f"Include remote roles: {config.include_remote}\n"
            f"Company: {company_name}\n\n"
            f"Jobs:\n{job_summaries}\n\n"
            "Return only jobs that reasonably match the target role, location, and experience level. "
            "Exclude jobs clearly outside the experience range (e.g. intern roles for senior searches). "
            "Assign match_score between 0 and 1 (1 = perfect match). "
            "Omit jobs with match_score below 0.4."
        )

        try:
            result = self._gemini.generate_structured(
                prompt=prompt,
                schema=ScoredJobList,
                system_instruction=(
                    "You are a job matching assistant. "
                    "Be inclusive of related engineering titles but exclude clearly unrelated roles "
                    "or experience levels."
                ),
            )
        except Exception as exc:
            logger.warning("LLM scoring failed for %s: %s", company_name, exc)
            return [
                (self._to_listing(job, company_name, ats_type, careers_url, score=0.5), job)
                for job in raw_jobs
            ]

        pairs: list[tuple[JobListing, RawJob]] = []
        for scored in result.jobs:
            if scored.match_score < 0.4:
                continue
            raw = next((j for j in raw_jobs if j.apply_url == scored.apply_url), None)
            if not raw:
                continue
            pairs.append(
                (
                    JobListing(
                        title=scored.title,
                        company=company_name,
                        location=scored.location,
                        department=scored.department,
                        apply_url=scored.apply_url,
                        posted_at=raw.posted_at,
                        ats=ats_type,  # type: ignore[arg-type]
                        source_company_url=careers_url,
                        match_score=scored.match_score,
                    ),
                    raw,
                )
            )
        return pairs

    def _to_listing(
        self,
        job: RawJob,
        company_name: str,
        ats_type: str,
        careers_url: str,
        score: float,
    ) -> JobListing:
        return JobListing(
            title=job.title,
            company=company_name,
            location=job.location,
            department=job.department,
            apply_url=job.apply_url,
            posted_at=job.posted_at,
            ats=ats_type,  # type: ignore[arg-type]
            source_company_url=careers_url,
            match_score=score,
        )
