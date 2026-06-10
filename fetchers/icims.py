import html
import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import httpx

from fetchers._html import extract_anchor_jobs
from fetchers.base import Fetcher
from fetchers.page_loader import fetch_page, parse_icims_network_jobs
from models.job import RawJob

if TYPE_CHECKING:
    from agent.worker_client import WorkerClient

logger = logging.getLogger(__name__)

ICIMS_IFRAME_SEARCH = "https://{token}.icims.com/jobs/search?pr={page}&in_iframe=1"
ICIMS_FALLBACK_URLS = (
    "https://{token}.icims.com/jobs/intro?in_iframe=1",
)

ICIMS_JOB_ANCHOR = re.compile(
    r'<a([^>]*\bclass="[^"]*\biCIMS_Anchor\b[^"]*"[^>]*)>',
    re.IGNORECASE,
)
HREF_ATTR = re.compile(r'\bhref="([^"]+)"', re.IGNORECASE)
TITLE_ATTR = re.compile(r'\btitle="([^"]+)"', re.IGNORECASE)
JOB_ID_PATTERN = re.compile(r"/jobs/(\d+)", re.IGNORECASE)


class IcimsFetcher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        worker: "WorkerClient | None" = None,
    ):
        self._client = client or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                # iCIMS serves a human-verification challenge to common bot UAs.
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        self._worker = worker

    def fetch_jobs(self, board_token: str) -> list[RawJob]:
        jobs = self._fetch_iframe_pages(board_token)
        if jobs:
            return jobs

        for url_template in ICIMS_FALLBACK_URLS:
            url = url_template.format(token=board_token)
            jobs = self._fetch_with_worker(url)
            if jobs:
                return jobs

        logger.info("No iCIMS jobs parsed for %s", board_token)
        return []

    def _fetch_iframe_pages(self, board_token: str) -> list[RawJob]:
        jobs: list[RawJob] = []
        seen: set[str] = set()

        for page in range(50):
            url = ICIMS_IFRAME_SEARCH.format(token=board_token, page=page)
            try:
                response = self._client.get(url)
            except httpx.HTTPError as exc:
                logger.info("iCIMS fetch failed for %s page %s: %s", board_token, page, exc)
                break

            if response.status_code >= 400:
                break

            page_jobs = parse_icims_iframe_jobs(response.text, str(response.url))
            if not page_jobs:
                break

            new_jobs = 0
            for job in page_jobs:
                if job.apply_url in seen:
                    continue
                seen.add(job.apply_url)
                jobs.append(job)
                new_jobs += 1

            if new_jobs == 0:
                break

        return jobs

    def _fetch_with_worker(self, url: str) -> list[RawJob]:
        page = fetch_page(
            url,
            httpx_client=self._client,
            worker=self._worker,
            capture_network=True,
        )

        if not page.ok and self._worker:
            page = fetch_page(
                url,
                httpx_client=self._client,
                worker=self._worker,
                capture_network=True,
                force_worker=True,
            )

        network_jobs = parse_icims_network_jobs(page.network_responses)
        if network_jobs:
            return network_jobs

        if not page.ok:
            return []

        iframe_jobs = parse_icims_iframe_jobs(page.html, page.final_url or url)
        if iframe_jobs:
            return iframe_jobs

        html_jobs = extract_anchor_jobs(
            page.html,
            page.final_url or url,
            href_pattern=r'[^"\']*icims\.com/jobs/\d+[^"\']*',
            ats_type="icims",
        )
        if html_jobs:
            return html_jobs

        return _extract_icims_html_job_ids(page.html, page.final_url or url)


def parse_icims_iframe_jobs(page_html: str, base_url: str) -> list[RawJob]:
    jobs: list[RawJob] = []
    seen: set[str] = set()

    for match in ICIMS_JOB_ANCHOR.finditer(page_html):
        attrs = match.group(1)
        if "iCIMS_Anchor_Nav" in attrs:
            continue

        href_match = HREF_ATTR.search(attrs)
        if not href_match:
            continue

        href = html.unescape(href_match.group(1))
        if "/jobs/" not in href or "/intro" in href:
            continue

        job_id_match = JOB_ID_PATTERN.search(href)
        if not job_id_match:
            continue

        apply_url = urljoin(base_url, href)
        if apply_url in seen:
            continue
        seen.add(apply_url)

        title_match = TITLE_ATTR.search(attrs)
        title = html.unescape(title_match.group(1)) if title_match else f"Job {job_id_match.group(1)}"

        jobs.append(
            RawJob(
                title=title,
                location=None,
                department=None,
                apply_url=apply_url,
                posted_at=None,
                raw_data={
                    "job_id": job_id_match.group(1),
                    "apply_url": apply_url,
                    "title": title,
                },
            )
        )

    return jobs


def _extract_icims_html_job_ids(page_html: str, base_url: str) -> list[RawJob]:
    jobs: list[RawJob] = []
    seen: set[str] = set()
    host_match = re.search(r"https?://([^/]+\.icims\.com)", base_url, re.IGNORECASE)
    if not host_match:
        return jobs

    host = host_match.group(1)
    for job_id in re.findall(r"/jobs/(\d+)", page_html):
        apply_url = f"https://{host}/jobs/{job_id}"
        if apply_url in seen:
            continue
        seen.add(apply_url)
        jobs.append(
            RawJob(
                title=f"Job {job_id}",
                location=None,
                department=None,
                apply_url=apply_url,
                posted_at=None,
                raw_data={"job_id": job_id, "apply_url": apply_url},
            )
        )

    return jobs


def create_icims_fetcher(
    client: httpx.Client | None = None,
    worker: "WorkerClient | None" = None,
) -> Fetcher:
    return IcimsFetcher(client, worker=worker)
