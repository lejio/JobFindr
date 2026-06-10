import logging
from typing import TYPE_CHECKING

import httpx

from fetchers._html import extract_anchor_jobs
from fetchers.base import Fetcher
from fetchers.page_loader import (
    JOBVITE_HEADERS,
    JOBVITE_SCRAPE_OPTIONS,
    fetch_page,
    parse_jobvite_html_jobs,
    parse_jobvite_network_jobs,
)
from models.job import RawJob

if TYPE_CHECKING:
    from agent.worker_client import WorkerClient

logger = logging.getLogger(__name__)

JOBVITE_BOARD_URLS = (
    "https://jobs.jobvite.com/{token}/jobs",
    "https://jobs.jobvite.com/{token}",
)


class JobviteFetcher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        worker: "WorkerClient | None" = None,
    ):
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True)
        self._worker = worker

    def fetch_jobs(self, board_token: str) -> list[RawJob]:
        for url_template in JOBVITE_BOARD_URLS:
            url = url_template.format(token=board_token)
            jobs = self._fetch_from_url(url)
            if jobs:
                return jobs

        logger.info("No Jobvite jobs parsed for %s", board_token)
        return []

    def _fetch_from_url(self, url: str) -> list[RawJob]:
        page = fetch_page(
            url,
            httpx_client=self._client,
            worker=self._worker,
            capture_network=True,
            headers=JOBVITE_HEADERS,
            scrape_options=JOBVITE_SCRAPE_OPTIONS,
        )

        jobs = _parse_jobvite_page(page.html, page.final_url or url)
        if jobs:
            return jobs

        network_jobs = parse_jobvite_network_jobs(page.network_responses)
        if network_jobs:
            return network_jobs

        if page.ok or page.network_responses:
            return []

        if not self._worker:
            return []

        page = fetch_page(
            url,
            httpx_client=self._client,
            worker=self._worker,
            capture_network=True,
            force_worker=True,
            headers=JOBVITE_HEADERS,
            scrape_options=JOBVITE_SCRAPE_OPTIONS,
        )

        jobs = _parse_jobvite_page(page.html, page.final_url or url)
        if jobs:
            return jobs

        return parse_jobvite_network_jobs(page.network_responses)


def _parse_jobvite_page(page_html: str, base_url: str) -> list[RawJob]:
    jobs = parse_jobvite_html_jobs(page_html, base_url)
    if jobs:
        return jobs

    return extract_anchor_jobs(
        page_html,
        base_url,
        href_pattern=r'[^"\']*(?:jobvite\.com)?[^"\']*/job/[^"\']+',
        ats_type="jobvite",
    )


def create_jobvite_fetcher(
    client: httpx.Client | None = None,
    worker: "WorkerClient | None" = None,
) -> Fetcher:
    return JobviteFetcher(client, worker=worker)
