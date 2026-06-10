import httpx

from fetchers.base import Fetcher
from fetchers.job_dates import extract_posted_at
from models.job import RawJob

WORKABLE_API = "https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"


class WorkableFetcher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30.0)

    def fetch_jobs(self, board_token: str) -> list[RawJob]:
        url = WORKABLE_API.format(token=board_token)
        response = self._client.get(url)
        response.raise_for_status()
        data = response.json()

        jobs: list[RawJob] = []
        for job in data.get("jobs", []):
            location_parts = [
                job.get("city"),
                job.get("state"),
                job.get("country"),
            ]
            location = ", ".join(part for part in location_parts if part) or None

            jobs.append(
                RawJob(
                    title=job.get("title", ""),
                    location=location,
                    department=job.get("department"),
                    apply_url=job.get("application_url") or job.get("url", ""),
                    posted_at=extract_posted_at("workable", job),
                    raw_data=job,
                )
            )
        return jobs


def create_workable_fetcher(client: httpx.Client | None = None) -> Fetcher:
    return WorkableFetcher(client)
