import httpx

from fetchers.base import Fetcher
from fetchers.job_dates import extract_posted_at
from models.job import RawJob

SMARTRECRUITERS_API = (
    "https://api.smartrecruiters.com/v1/companies/{token}/postings"
)


class SmartRecruitersFetcher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30.0)

    def fetch_jobs(self, board_token: str) -> list[RawJob]:
        jobs: list[RawJob] = []
        offset = 0
        limit = 100

        while True:
            response = self._client.get(
                SMARTRECRUITERS_API.format(token=board_token),
                params={"limit": limit, "offset": offset},
            )
            if response.status_code == 404:
                return jobs
            response.raise_for_status()
            data = response.json()

            batch = data.get("content", [])
            if not batch:
                break

            for posting in batch:
                location = posting.get("location") or {}
                location_text = location.get("fullLocation")
                if not location_text:
                    parts = [location.get("city"), location.get("region"), location.get("country")]
                    location_text = ", ".join(p for p in parts if p) or None

                department = posting.get("department") or {}
                apply_url = (
                    f"https://jobs.smartrecruiters.com/{board_token}/{posting.get('id')}"
                )

                jobs.append(
                    RawJob(
                        title=posting.get("name", ""),
                        location=location_text,
                        department=department.get("label"),
                        apply_url=apply_url,
                        posted_at=extract_posted_at("smartrecruiters", posting),
                        raw_data=posting,
                    )
                )

            offset += len(batch)
            if offset >= data.get("totalFound", 0):
                break

        return jobs


def create_smartrecruiters_fetcher(client: httpx.Client | None = None) -> Fetcher:
    return SmartRecruitersFetcher(client)
