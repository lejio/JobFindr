import httpx

from fetchers.base import Fetcher
from fetchers.job_dates import extract_posted_at
from models.job import RawJob

BAMBOOHR_LIST_API = "https://{token}.bamboohr.com/careers/list"


class BamboohrFetcher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    def fetch_jobs(self, board_token: str) -> list[RawJob]:
        url = BAMBOOHR_LIST_API.format(token=board_token)
        response = self._client.get(url)
        if response.status_code in {403, 404}:
            return []
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            return []

        data = response.json()
        jobs: list[RawJob] = []

        for job in data.get("result", []):
            location_data = job.get("location") or {}
            location_parts = [
                location_data.get("city"),
                location_data.get("state"),
            ]
            location = ", ".join(part for part in location_parts if part) or None
            if job.get("isRemote"):
                location = f"{location} (Remote)" if location else "Remote"

            job_id = job.get("id")
            apply_url = f"https://{board_token}.bamboohr.com/careers/{job_id}"

            jobs.append(
                RawJob(
                    title=job.get("jobOpeningName", ""),
                    location=location,
                    department=job.get("departmentLabel"),
                    apply_url=apply_url,
                    posted_at=extract_posted_at("bamboohr", job),
                    raw_data=job,
                )
            )

        return jobs


def create_bamboohr_fetcher(client: httpx.Client | None = None) -> Fetcher:
    return BamboohrFetcher(client)
