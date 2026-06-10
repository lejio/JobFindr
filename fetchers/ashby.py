import httpx

from fetchers.base import Fetcher
from fetchers.job_dates import extract_posted_at
from models.job import RawJob

ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{org}"


class AshbyFetcher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30.0)

    def fetch_jobs(self, board_token: str) -> list[RawJob]:
        url = ASHBY_API.format(org=board_token)
        response = self._client.get(url)
        response.raise_for_status()
        data = response.json()

        jobs: list[RawJob] = []
        for job in data.get("jobs", []):
            location = job.get("location")
            if isinstance(location, dict):
                location = location.get("name") or location.get("location")

            jobs.append(
                RawJob(
                    title=job.get("title", ""),
                    location=location,
                    department=job.get("department"),
                    apply_url=job.get("jobUrl", job.get("applyUrl", "")),
                    posted_at=extract_posted_at("ashby", job),
                    raw_data=job,
                )
            )
        return jobs


def create_ashby_fetcher(client: httpx.Client | None = None) -> Fetcher:
    return AshbyFetcher(client)
