import httpx

from fetchers.base import Fetcher
from fetchers.job_dates import extract_posted_at
from models.job import RawJob

LEVER_API = "https://api.lever.co/v0/postings/{company}?mode=json"


class LeverFetcher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30.0)

    def fetch_jobs(self, board_token: str) -> list[RawJob]:
        url = LEVER_API.format(company=board_token)
        response = self._client.get(url)
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, list):
            return []

        jobs: list[RawJob] = []
        for posting in data:
            categories = posting.get("categories", {})
            location = categories.get("location")
            department = categories.get("department") or categories.get("team")

            jobs.append(
                RawJob(
                    title=posting.get("text", ""),
                    location=location,
                    department=department,
                    apply_url=posting.get("hostedUrl", posting.get("applyUrl", "")),
                    posted_at=extract_posted_at("lever", posting),
                    raw_data=posting,
                )
            )
        return jobs


def create_lever_fetcher(client: httpx.Client | None = None) -> Fetcher:
    return LeverFetcher(client)
