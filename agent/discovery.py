import logging
import time

import httpx
from pydantic import BaseModel, Field

from agent.gemini_client import GeminiClient
from agent.vc_portfolio import VCPortfolioDiscovery
from agent.worker_client import WorkerClient
from config import AppSettings, SearchConfig
from fetchers.ats_detector import detect_ats
from fetchers.ats_probe import resolve_company_ats
from models.job import CompanyTarget
from models.portfolio import PortfolioCompany

logger = logging.getLogger(__name__)

ATS_SITES = {
    # Modern / tech favorites
    "greenhouse": "site:boards.greenhouse.io",
    "lever": "site:jobs.lever.co",
    "ashby": "site:jobs.ashbyhq.com",
    "workable": "site:apply.workable.com",
    "teamtailor": "site:*.teamtailor.com/jobs",
    # Enterprise giants
    "workday": (
        "site:*.wd1.myworkdayjobs.com OR site:*.wd3.myworkdayjobs.com "
        "OR site:*.wd5.myworkdayjobs.com"
    ),
    "icims": "site:*.icims.com/jobs",
    "taleo": "site:*.taleo.net/careersection",
    "successfactors": "site:jobs.sap.com OR site:*.jobs2web.com",
    "smartrecruiters": "site:jobs.smartrecruiters.com",
    "jobvite": "site:jobs.jobvite.com",
    # HRIS and all-in-one platforms
    "rippling": "site:ats.rippling.com/jobs",
    "bamboohr": "site:*.bamboohr.com/careers OR site:*.bamboohr.com/jobs",
}

BROAD_ATS_SITE_FILTER = (
    "site:boards.greenhouse.io OR site:jobs.lever.co OR site:jobs.ashbyhq.com "
    "OR site:apply.workable.com OR site:jobs.smartrecruiters.com "
    "OR site:ats.rippling.com/jobs"
)

STARTUP_ATS_PRIORITY = ("greenhouse", "lever", "ashby")
ENTERPRISE_ATS_PRIORITY = ("workday", "icims", "successfactors")


class DiscoveredCompany(BaseModel):
    name: str
    industry: str | None = None
    stage: str | None = None
    rationale: str | None = None
    website: str | None = None


class CompanyDiscoveryResult(BaseModel):
    companies: list[DiscoveredCompany] = Field(default_factory=list)


class CompanyDiscovery:
    def __init__(
        self,
        settings: AppSettings,
        gemini: GeminiClient,
        worker: WorkerClient | None = None,
    ):
        self._settings = settings
        self._gemini = gemini
        self._worker = worker or WorkerClient(settings)
        self._owns_worker = worker is None
        self._vc_discovery = VCPortfolioDiscovery(gemini, self._worker)
        self._http = httpx.Client(timeout=15.0, follow_redirects=True)
        self._search_config: SearchConfig | None = None

    def discover_companies(self, config: SearchConfig) -> list[CompanyTarget]:
        self._search_config = config

        if config.direct_targets:
            return config.direct_targets

        if not self._worker.health_check():
            raise RuntimeError(
                "Stealth worker is not running. Start it with: cd worker && npm start"
            )

        if config.use_vc_discovery:
            return self._discover_via_vc_portfolios(config)

        return self._discover_via_gemini(config)

    def _discover_via_vc_portfolios(self, config: SearchConfig) -> list[CompanyTarget]:
        portfolio_companies = self._vc_discovery.discover(config)
        logger.info(
            "VC portfolio discovery found %d companies (saved to data/target_companies.json)",
            len(portfolio_companies),
        )

        targets: list[CompanyTarget] = []
        for company in portfolio_companies:
            if len(targets) >= config.max_companies:
                break

            resolved = self._resolve_ats_url(
                DiscoveredCompany(
                    name=company.name,
                    rationale=f"Portfolio company from {company.source_vc}",
                    website=company.website,
                ),
                config,
            )
            if resolved:
                targets.append(resolved)
            else:
                logger.info("No ATS board found for %s", company.name)

            time.sleep(0.5)

        return targets

    def _discover_via_gemini(self, config: SearchConfig) -> list[CompanyTarget]:
        experience = config.experience or "any experience level"
        post_time = (
            f"actively posting roles within the last {config.posted_within_days} days"
            if config.posted_within_days is not None
            else "actively hiring"
        )

        prompt = (
            f"Generate a list of real, currently operating companies that match this job search profile.\n\n"
            f"Role: {config.role}\n"
            f"Location: {config.location}\n"
            f"Experience level: {experience}\n"
            f"Hiring recency: {post_time}\n"
            f"Company profile: {config.company_profile}\n"
            f"Include remote-friendly companies: {config.include_remote}\n"
            f"Maximum companies: {config.max_companies}\n\n"
            "Return well-known companies that are likely to have public career pages "
            "on Greenhouse, Lever, or Ashby ATS platforms."
        )

        result = self._gemini.generate_structured(
            prompt=prompt,
            schema=CompanyDiscoveryResult,
            system_instruction=(
                "You are a job market research assistant. "
                "Return only real companies that actively hire for the given profile."
            ),
        )

        targets: list[CompanyTarget] = []
        for company in result.companies[: config.max_companies]:
            resolved = self._resolve_ats_url(company, config)
            if resolved:
                targets.append(resolved)
            else:
                logger.info("No ATS board found for %s", company.name)
            time.sleep(0.5)

        return targets

    def _resolve_ats_url(
        self,
        company: DiscoveredCompany,
        config: SearchConfig,
    ) -> CompanyTarget | None:
        probed = resolve_company_ats(company.name, company.website, client=self._http)
        if probed:
            probed.industry = company.industry
            probed.stage = company.stage
            probed.rationale = company.rationale
            logger.info("Resolved %s via HTTP probe", company.name)
            return probed

        target = self._resolve_via_targeted_search(company, config)
        if target:
            return target

        return None

    def _resolve_via_targeted_search(
        self,
        company: DiscoveredCompany,
        config: SearchConfig,
    ) -> CompanyTarget | None:
        broad_query = f'"{company.name}" ({BROAD_ATS_SITE_FILTER})'
        target = self._search_and_detect(company, broad_query)
        if target:
            logger.info("Resolved %s via broad stealth search", company.name)
            return target

        for ats_type in self._ats_search_priority(config):
            site_filter = ATS_SITES.get(ats_type)
            if not site_filter:
                continue

            query = f'{site_filter} "{company.name}"'
            target = self._search_and_detect(company, query)
            if target:
                logger.info(
                    "Resolved %s via targeted stealth search (%s)",
                    company.name,
                    ats_type,
                )
                return target

        return None

    def _ats_search_priority(self, config: SearchConfig) -> tuple[str, ...]:
        profile = config.company_profile.lower()
        if any(
            keyword in profile
            for keyword in ("enterprise", "fortune", "global", "healthcare", "university")
        ):
            return ENTERPRISE_ATS_PRIORITY
        if any(
            keyword in profile
            for keyword in ("startup", "series", "seed", "vc", "tech")
        ):
            return STARTUP_ATS_PRIORITY
        return STARTUP_ATS_PRIORITY

    def _search_and_detect(
        self,
        company: DiscoveredCompany,
        query: str,
    ) -> CompanyTarget | None:
        urls = self._stealth_google_search(query)
        for url in urls:
            detected = detect_ats(url)
            if not detected:
                continue

            detected_type, board_token, canonical_url = detected
            return CompanyTarget(
                name=company.name,
                industry=company.industry,
                stage=company.stage,
                rationale=company.rationale,
                ats_type=detected_type,
                board_token=board_token,
                careers_url=canonical_url,
            )

        return None

    def _stealth_google_search(self, query: str) -> list[str]:
        try:
            return self._worker.google_search(query, max_results=5)
        except Exception as exc:
            logger.warning("Stealth search failed for query %r: %s", query, exc)
            return []

    def get_proxy_traffic_stats(self):
        return self._worker.traffic.to_stats()

    def close(self) -> None:
        self._vc_discovery.close()
        self._http.close()
        if self._owns_worker:
            self._worker.close()
