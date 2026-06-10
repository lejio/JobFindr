import logging

import httpx

from fetchers._html import extract_anchor_jobs
from fetchers.base import Fetcher
from models.job import RawJob

logger = logging.getLogger(__name__)


class SuccessfactorsFetcher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
        )

    def fetch_jobs(self, board_token: str) -> list[RawJob]:
        if board_token in {"jobs", "search", "sap"} or "." not in board_token:
            board_url = "https://jobs.sap.com/search/"
            href_pattern = r'/job/[^"\']+/\d+/?'
        else:
            board_url = f"https://{board_token}.jobs2web.com/"
            href_pattern = r'/(?:job|go)/[^"\']+/\d+/?'

        try:
            response = self._client.get(board_url)
            if response.status_code in {403, 404}:
                logger.info(
                    "SuccessFactors board unavailable for %s (HTTP %s)",
                    board_token,
                    response.status_code,
                )
                return []
            if response.status_code >= 400:
                logger.info(
                    "SuccessFactors board unavailable for %s (HTTP %s)",
                    board_token,
                    response.status_code,
                )
                return []
        except httpx.HTTPError as exc:
            logger.info("SuccessFactors fetch failed for %s: %s", board_token, exc)
            return []

        jobs = extract_anchor_jobs(
            response.text,
            str(response.url),
            href_pattern=href_pattern,
            ats_type="successfactors",
        )
        if not jobs:
            logger.info("No SuccessFactors jobs parsed for %s", board_token)
        return jobs


def create_successfactors_fetcher(client: httpx.Client | None = None) -> Fetcher:
    return SuccessfactorsFetcher(client)
