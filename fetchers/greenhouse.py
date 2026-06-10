import httpx

from fetchers.base import Fetcher
from fetchers.job_dates import extract_posted_at
from models.job import RawJob

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


class GreenhouseFetcher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30.0)

    def fetch_jobs(self, board_token: str) -> list[RawJob]:
        url = GREENHOUSE_API.format(token=board_token)
        response = self._client.get(url)
        response.raise_for_status()
        data = response.json()

        jobs: list[RawJob] = []
        for job in data.get("jobs", []):
            location = job.get("location", {}).get("name")
            departments = job.get("departments", [])
            department = departments[0].get("name") if departments else None

            jobs.append(
                RawJob(
                    title=job.get("title", ""),
                    location=location,
                    department=department,
                    apply_url=job.get("absolute_url", ""),
                    posted_at=extract_posted_at("greenhouse", job),
                    raw_data=job,
                )
            )
        return jobs


def create_greenhouse_fetcher(client: httpx.Client | None = None) -> Fetcher:
    return GreenhouseFetcher(client)
