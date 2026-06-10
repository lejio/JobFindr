from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from fetchers.ats_types import AtsType
from models.usage import UsageStats


class CompanyTarget(BaseModel):
    name: str
    industry: str | None = None
    stage: str | None = None
    rationale: str | None = None
    ats_type: AtsType | None = None
    board_token: str | None = None
    careers_url: str | None = None


class RawJob(BaseModel):
    title: str
    location: str | None = None
    department: str | None = None
    apply_url: str
    posted_at: datetime | None = None
    raw_data: dict = Field(default_factory=dict)


class JobListing(BaseModel):
    title: str
    company: str
    location: str | None = None
    department: str | None = None
    apply_url: str
    posted_at: datetime | None = None
    ats: AtsType
    source_company_url: str
    match_score: float | None = None
    qualify_score: int | None = None
    qualify_rationale: str | None = None
    qualify_scored_with: Literal["title", "full"] | None = None


class ParsedJob(BaseModel):
    listing: JobListing
    raw: RawJob
    ats_type: AtsType
    board_token: str


class CompanyError(BaseModel):
    company: str
    error: str


class SearchResult(BaseModel):
    config_role: str
    config_location: str
    config_company_profile: str
    config_experience: str | None = None
    config_posted_within_days: int | None = None
    searched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    vc_firms_used: list[str] = Field(default_factory=list)
    target_companies_count: int = 0
    companies_discovered: int = 0
    companies_with_ats: int = 0
    companies_searched: list[str] = Field(default_factory=list)
    ats_breakdown: dict[str, int] = Field(default_factory=dict)
    jobs: list[JobListing] = Field(default_factory=list)
    errors: list[CompanyError] = Field(default_factory=list)
    usage: UsageStats = Field(default_factory=UsageStats)
    resume_scoring_enabled: bool = False
    resume_cache_used: bool = False
    jobs_title_scored: int = 0
    jobs_full_scored: int = 0
