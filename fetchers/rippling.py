import logging

import httpx

from fetchers.base import Fetcher
from models.job import RawJob

logger = logging.getLogger(__name__)

RIPPLING_API = "https://ats.rippling.com/api/v2/board/{token}/jobs"
PAGE_SIZE = 100


class RipplingFetcher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
        )

    def fetch_jobs(self, board_token: str) -> list[RawJob]:
        jobs: list[RawJob] = []
        page = 0

        while page < 50:
            try:
                response = self._client.get(
                    RIPPLING_API.format(token=board_token),
                    params={"page": page, "pageSize": PAGE_SIZE},
                )
            except httpx.HTTPError as exc:
                logger.info("Rippling fetch failed for %s: %s", board_token, exc)
                return jobs

            if response.status_code == 404:
                return jobs
            if response.status_code >= 400:
                logger.info(
                    "Rippling board unavailable for %s (HTTP %s)",
                    board_token,
                    response.status_code,
                )
                return jobs

            data = response.json()
            batch = data.get("items", [])
            if not batch:
                break

            for item in batch:
                jobs.append(
                    RawJob(
                        title=item.get("name", ""),
                        location=_format_locations(item.get("locations")),
                        department=(item.get("department") or {}).get("name"),
                        apply_url=item.get("url", ""),
                        posted_at=None,
                        raw_data=item,
                    )
                )

            total_pages = data.get("totalPages", page + 1)
            page += 1
            if page >= total_pages:
                break

        if not jobs:
            logger.info("No Rippling jobs parsed for %s", board_token)
        return jobs


def _format_locations(locations: list | None) -> str | None:
    if not locations:
        return None
    names = [loc.get("name") for loc in locations if isinstance(loc, dict) and loc.get("name")]
    return ", ".join(names) if names else None


def create_rippling_fetcher(client: httpx.Client | None = None) -> Fetcher:
    return RipplingFetcher(client)
