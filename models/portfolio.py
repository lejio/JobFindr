from datetime import datetime, timezone

from pydantic import BaseModel, Field


class PortfolioCompany(BaseModel):
    name: str
    website: str | None = None
    source_vc: str
    location_hint: str | None = None


class TargetCompaniesStore(BaseModel):
    search_location: str
    vc_firms_used: list[str] = Field(default_factory=list)
    companies: list[PortfolioCompany] = Field(default_factory=list)
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
