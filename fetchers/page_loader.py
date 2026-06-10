import html
import json
import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import httpx

from models.job import RawJob

if TYPE_CHECKING:
    from agent.worker_client import WorkerClient

logger = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

MIN_HTML_LEN = 500

INVALID_URL_MARKERS = (
    "invalid=1",
    "jobvite.com/support",
    "search.jobvite.com",
)


class PageFetchResult:
    def __init__(
        self,
        html: str = "",
        final_url: str = "",
        network_responses: list[dict] | None = None,
    ):
        self.html = html
        self.final_url = final_url
        self.network_responses = network_responses or []

    @property
    def ok(self) -> bool:
        return len(self.html) >= MIN_HTML_LEN


def _is_invalid_final_url(url: str) -> bool:
    lower = url.lower()
    return any(marker in lower for marker in INVALID_URL_MARKERS)


def _fetch_via_httpx(
    url: str,
    client: httpx.Client,
    *,
    headers: dict[str, str] | None = None,
) -> PageFetchResult:
    try:
        response = client.get(
            url,
            headers=headers or BROWSER_HEADERS,
            follow_redirects=True,
        )
        final_url = str(response.url)

        if _is_invalid_final_url(final_url):
            logger.info("Invalid redirect for %s -> %s", url, final_url)
            return PageFetchResult()

        if response.status_code in {403, 404, 405} or response.status_code >= 500:
            logger.info("HTTP %s for %s", response.status_code, url)
            return PageFetchResult()

        if response.status_code >= 400:
            logger.info("HTTP %s for %s", response.status_code, url)
            return PageFetchResult()

        return PageFetchResult(html=response.text, final_url=final_url)
    except httpx.HTTPError as exc:
        logger.info("HTTP fetch failed for %s: %s", url, exc)
        return PageFetchResult()


def _fetch_via_worker(
    url: str,
    worker: "WorkerClient",
    *,
    capture_network: bool,
    scrape_options: dict | None = None,
) -> PageFetchResult:
    try:
        if not worker.health_check():
            logger.info("Worker unavailable for scrape of %s", url)
            return PageFetchResult()

        result = worker.scrape(
            url,
            capture_network=capture_network,
            scrape_options=scrape_options,
        )
        html = result.get("html", "")
        final_url = result.get("url", url)
        network = result.get("network_responses", [])

        if _is_invalid_final_url(final_url):
            logger.info("Worker scrape invalid redirect for %s -> %s", url, final_url)
            return PageFetchResult(network_responses=network)

        return PageFetchResult(html=html, final_url=final_url, network_responses=network)
    except Exception as exc:
        logger.warning("Worker scrape failed for %s: %s", url, exc)
        return PageFetchResult()


def fetch_page(
    url: str,
    *,
    httpx_client: httpx.Client,
    worker: "WorkerClient | None" = None,
    capture_network: bool = False,
    force_worker: bool = False,
    headers: dict[str, str] | None = None,
    scrape_options: dict | None = None,
) -> PageFetchResult:
    if not force_worker:
        result = _fetch_via_httpx(url, httpx_client, headers=headers)
        if result.ok:
            return result

    if worker:
        worker_result = _fetch_via_worker(
            url,
            worker,
            capture_network=capture_network,
            scrape_options=scrape_options,
        )
        if worker_result.ok:
            return worker_result
        if worker_result.network_responses and not worker_result.html:
            return worker_result

    if not force_worker:
        return result
    return PageFetchResult()


def parse_icims_network_jobs(network_responses: list[dict]) -> list[RawJob]:
    jobs: list[RawJob] = []
    seen_urls: set[str] = set()

    for entry in network_responses:
        body = entry.get("body", "")
        if not body or "icims" not in entry.get("url", "").lower():
            continue

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue

        candidates = _extract_icims_job_dicts(data)
        for item in candidates:
            title = (
                item.get("jobtitle")
                or item.get("title")
                or item.get("jobTitle")
                or item.get("name")
                or ""
            ).strip()
            job_id = item.get("jobid") or item.get("jobId") or item.get("id")
            apply_url = (
                item.get("url")
                or item.get("link")
                or item.get("applyUrl")
                or item.get("joblocation")
            )

            if not apply_url and job_id:
                host = _icims_host_from_network(entry.get("url", ""))
                if host:
                    apply_url = f"https://{host}/jobs/{job_id}"

            if not title or not apply_url:
                continue

            apply_url = str(apply_url)
            if apply_url in seen_urls:
                continue
            if not re.search(r"/jobs/\d+", apply_url, re.IGNORECASE):
                continue

            seen_urls.add(apply_url)
            location = item.get("location") or item.get("joblocation")
            if isinstance(location, dict):
                location = location.get("city") or location.get("name")

            jobs.append(
                RawJob(
                    title=title,
                    location=str(location) if location else None,
                    department=item.get("department") or item.get("category"),
                    apply_url=apply_url,
                    posted_at=None,
                    raw_data=item if isinstance(item, dict) else {"raw": item},
                )
            )

    return jobs


def _icims_host_from_network(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc and "icims.com" in parsed.netloc:
        return parsed.netloc
    return None


def _extract_icims_job_dicts(data: object) -> list[dict]:
    found: list[dict] = []

    if isinstance(data, dict):
        for key in ("jobs", "results", "jobList", "postings", "items"):
            value = data.get(key)
            if isinstance(value, list):
                found.extend(item for item in value if isinstance(item, dict))

        if data.get("jobtitle") or data.get("jobTitle"):
            found.append(data)

        for value in data.values():
            if isinstance(value, (dict, list)):
                found.extend(_extract_icims_job_dicts(value))

    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                found.extend(_extract_icims_job_dicts(item))

    return found


JOBVITE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml",
}

JOBVITE_SCRAPE_OPTIONS = {
    "force_full_load": True,
    "timeout": 60000,
}


def parse_jobvite_html_jobs(page_html: str, base_url: str) -> list[RawJob]:
    jobs: list[RawJob] = []
    seen_urls: set[str] = set()

    anchor_pattern = re.compile(
        r'<a([^>]*href=["\']([^"\']*/job/[^"\']+)["\'][^>]*)>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    title_attr_pattern = re.compile(r'\btitle=["\']([^"\']+)["\']', re.IGNORECASE)

    for match in anchor_pattern.finditer(page_html):
        attrs = match.group(1)
        href = match.group(2).strip()
        if "support" in href.lower() or "/jobs/" in href.lower():
            continue

        apply_url = urljoin(base_url, href)
        if apply_url in seen_urls:
            continue
        if "jobvite.com" not in apply_url.lower():
            continue
        if not re.search(r"/job/[^/]+$", apply_url, re.IGNORECASE):
            continue

        title_match = title_attr_pattern.search(attrs)
        if title_match:
            title = html.unescape(title_match.group(1)).strip()
        else:
            title = _html_to_text(match.group(3))

        if len(title) < 2:
            continue

        seen_urls.add(apply_url)
        jobs.append(
            RawJob(
                title=title,
                location=None,
                department=None,
                apply_url=apply_url,
                posted_at=None,
                raw_data={"title": title, "apply_url": apply_url},
            )
        )

    return jobs


def parse_jobvite_network_jobs(network_responses: list[dict]) -> list[RawJob]:
    jobs: list[RawJob] = []
    seen_urls: set[str] = set()

    for entry in network_responses:
        body = entry.get("body", "")
        response_url = entry.get("url", "")
        if not body or "jobvite.com" not in response_url.lower():
            continue

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue

        candidates = _extract_jobvite_job_dicts(data)
        host = _jobvite_host_from_network(response_url)
        for item in candidates:
            title = (
                item.get("title")
                or item.get("jobTitle")
                or item.get("name")
                or item.get("positionTitle")
                or ""
            ).strip()
            job_id = (
                item.get("jobId")
                or item.get("requisitionId")
                or item.get("eId")
                or item.get("id")
            )
            apply_url = item.get("applyUrl") or item.get("url") or item.get("link")

            if not apply_url and job_id and host:
                slug = _jobvite_slug_from_item(item) or _jobvite_slug_from_url(response_url)
                if slug:
                    apply_url = f"https://{host}/{slug}/job/{job_id}"

            if not title or not apply_url:
                continue

            apply_url = str(apply_url)
            if apply_url in seen_urls:
                continue
            if "/job/" not in apply_url.lower():
                continue

            seen_urls.add(apply_url)
            location = item.get("location") or item.get("jobLocation")
            if isinstance(location, dict):
                location = location.get("city") or location.get("name")

            jobs.append(
                RawJob(
                    title=title,
                    location=str(location) if location else None,
                    department=item.get("department") or item.get("category"),
                    apply_url=apply_url,
                    posted_at=None,
                    raw_data=item if isinstance(item, dict) else {"raw": item},
                )
            )

    return jobs


def _html_to_text(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = html.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _jobvite_host_from_network(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc and "jobvite.com" in parsed.netloc:
        return parsed.netloc
    return "jobs.jobvite.com"


def _jobvite_slug_from_url(url: str) -> str | None:
    match = re.search(r"jobs\.jobvite\.com/([^/?#]+)", url, re.IGNORECASE)
    return match.group(1).lower() if match else None


def _jobvite_slug_from_item(item: dict) -> str | None:
    for key in ("company", "companySlug", "careersiteName", "accountName"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def _extract_jobvite_job_dicts(data: object) -> list[dict]:
    found: list[dict] = []

    if isinstance(data, dict):
        for key in ("jobs", "requisitions", "results", "postings", "items", "positions"):
            value = data.get(key)
            if isinstance(value, list):
                found.extend(item for item in value if isinstance(item, dict))

        if any(data.get(field) for field in ("title", "jobTitle", "requisitionId", "jobId")):
            found.append(data)

        for value in data.values():
            if isinstance(value, (dict, list)):
                found.extend(_extract_jobvite_job_dicts(value))

    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                found.extend(_extract_jobvite_job_dicts(item))

    return found
