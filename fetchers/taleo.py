import logging

import httpx

from fetchers._html import extract_anchor_jobs
from fetchers.base import Fetcher
from models.job import RawJob

logger = logging.getLogger(__name__)

TALEO_JOB_LIST_URL = (
    "https://{host}.taleo.net/careersection/{section}/joblist.ftl"
)


class TaleoFetcher:
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
        host, section = _parse_board_token(board_token)
        url = TALEO_JOB_LIST_URL.format(host=host, section=section)
        response = self._client.get(url)
        if response.status_code in {403, 404}:
            logger.info("Taleo board unavailable for %s (HTTP %s)", board_token, response.status_code)
            return []

        response.raise_for_status()
        jobs = extract_anchor_jobs(
            response.text,
            str(response.url),
            href_pattern=r'[^"\']*taleo\.net/careersection/[^"\']+',
        )
        if not jobs:
            logger.info("No Taleo jobs parsed for %s", board_token)
        return jobs


def _parse_board_token(board_token: str) -> tuple[str, str]:
    if ":" in board_token:
        host, section = board_token.split(":", 1)
        return host, section
    return board_token, "2"


def create_taleo_fetcher(client: httpx.Client | None = None) -> Fetcher:
    return TaleoFetcher(client)
