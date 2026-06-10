import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import httpx

from agent.discovery import CompanyDiscovery
from agent.resume_loader import load_resume
from agent.resume_scorer import ResumeScorer
from agent.vc_portfolio import VCPortfolioDiscovery
from agent.gemini_client import GeminiClient
from agent.parser import JobParser
from agent.worker_client import WorkerClient
from config import AppSettings, SearchConfig
from fetchers.registry import FetcherRegistry
from models.job import CompanyError, CompanyTarget, ParsedJob, RawJob, SearchResult
from models.usage import UsageStats

logger = logging.getLogger(__name__)


@dataclass
class CompanyFetchResult:
    target: CompanyTarget
    raw_jobs: list[RawJob]
    error: str | None = None


class AgentOrchestrator:
    def __init__(self, settings: AppSettings):
        self._settings = settings
        self._gemini = GeminiClient(settings)
        self._worker = WorkerClient(settings)
        self._discovery = CompanyDiscovery(settings, self._gemini, worker=self._worker)
        self._parser = JobParser(self._gemini)
        self._fetchers = FetcherRegistry(worker=self._worker)
        self._resume_scorer = ResumeScorer(self._gemini, self._fetchers)

    def run(self, config: SearchConfig) -> SearchResult:
        result = SearchResult(
            config_role=config.role,
            config_location=config.location,
            config_company_profile=config.company_profile,
            config_experience=config.experience or None,
            config_posted_within_days=config.posted_within_days,
        )

        try:
            targets = self._discovery.discover_companies(config)
            store = VCPortfolioDiscovery.load_target_companies()
            if store:
                result.vc_firms_used = store.vc_firms_used
                result.target_companies_count = len(store.companies)
            result.companies_discovered = len(targets)

            fetch_results = self._fetch_companies_parallel(targets, config)
            all_parsed: list[ParsedJob] = []

            for fetch_result in fetch_results:
                target = fetch_result.target
                if fetch_result.error:
                    result.errors.append(
                        CompanyError(company=target.name, error=fetch_result.error)
                    )
                    continue

                result.companies_with_ats += 1
                result.companies_searched.append(target.name)
                if target.ats_type:
                    result.ats_breakdown[target.ats_type] = (
                        result.ats_breakdown.get(target.ats_type, 0) + 1
                    )

                try:
                    pairs = self._parser.parse_and_filter(
                        config=config,
                        company_name=target.name,
                        ats_type=target.ats_type or "",
                        careers_url=target.careers_url or "",
                        raw_jobs=fetch_result.raw_jobs,
                    )
                    for listing, raw in pairs:
                        all_parsed.append(
                            ParsedJob(
                                listing=listing,
                                raw=raw,
                                ats_type=target.ats_type or "",
                                board_token=target.board_token or "",
                            )
                        )
                    logger.info(
                        "Fetched %d jobs from %s (%s)",
                        len(pairs),
                        target.name,
                        target.ats_type,
                    )
                except Exception as exc:
                    logger.warning("Failed to parse jobs for %s: %s", target.name, exc)
                    result.errors.append(
                        CompanyError(company=target.name, error=str(exc))
                    )

            deduped = self._deduplicate_parsed(all_parsed)

            resume = None
            if config.resume_enabled:
                resume = load_resume(config.resume_path)

            if resume and config.resume_enabled:
                jobs, score_stats = self._resume_scorer.score_jobs(
                    resume, deduped, config
                )
                result.resume_scoring_enabled = True
                result.resume_cache_used = score_stats.resume_cache_used
                result.jobs_title_scored = score_stats.title_scored
                result.jobs_full_scored = score_stats.full_scored
                result.jobs = sorted(
                    jobs,
                    key=lambda j: (j.qualify_score or 0, j.match_score or 0.0),
                    reverse=True,
                )
            else:
                result.jobs = sorted(
                    [p.listing for p in deduped],
                    key=lambda j: j.match_score or 0.0,
                    reverse=True,
                )

            result.usage = self._collect_usage_stats()
        finally:
            self._discovery.close()
            self._fetchers.close()
            self._worker.close()

        return result

    def _fetch_companies_parallel(
        self,
        targets: list[CompanyTarget],
        config: SearchConfig,
    ) -> list[CompanyFetchResult]:
        valid_targets: list[CompanyTarget] = []
        results: list[CompanyFetchResult] = []

        for target in targets:
            if not target.ats_type or not target.board_token or not target.careers_url:
                results.append(
                    CompanyFetchResult(
                        target=target,
                        raw_jobs=[],
                        error="No ATS board resolved",
                    )
                )
            else:
                valid_targets.append(target)

        if not valid_targets:
            return results

        concurrency = max(1, config.fetch_concurrency)
        logger.info(
            "Fetching jobs for %d companies with concurrency=%d",
            len(valid_targets),
            concurrency,
        )

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(self._fetch_company_jobs, target): target
                for target in valid_targets
            }
            for future in as_completed(futures):
                target = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    logger.warning("Failed to fetch jobs for %s: %s", target.name, exc)
                    results.append(
                        CompanyFetchResult(
                            target=target,
                            raw_jobs=[],
                            error=str(exc),
                        )
                    )

        return results

    def _fetch_company_jobs(self, target: CompanyTarget) -> CompanyFetchResult:
        http = httpx.Client(
            timeout=30.0,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        worker_http = httpx.Client(
            base_url=self._settings.worker_url,
            timeout=self._settings.worker_timeout,
        )
        worker = WorkerClient(self._settings, client=worker_http)
        worker.traffic = self._worker.traffic

        try:
            registry = FetcherRegistry(
                client=http,
                worker=worker,
                min_delay=0,
                max_delay=0,
            )
            raw_jobs = registry.fetch_jobs(target.ats_type, target.board_token)
            return CompanyFetchResult(target=target, raw_jobs=raw_jobs)
        except Exception as exc:
            return CompanyFetchResult(target=target, raw_jobs=[], error=str(exc))
        finally:
            http.close()
            worker_http.close()

    def _collect_usage_stats(self) -> UsageStats:
        worker_traffic = self._discovery.get_proxy_traffic_stats()
        return UsageStats(
            tokens=self._gemini.usage.to_stats(),
            proxy=worker_traffic,
        )

    def _deduplicate_parsed(self, parsed_jobs: list[ParsedJob]) -> list[ParsedJob]:
        seen: set[str] = set()
        unique: list[ParsedJob] = []
        for parsed in parsed_jobs:
            if parsed.listing.apply_url in seen:
                continue
            seen.add(parsed.listing.apply_url)
            unique.append(parsed)
        return unique
