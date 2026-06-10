import httpx

from fetchers.base import Fetcher
from fetchers.job_dates import extract_posted_at
from models.job import RawJob

WORKDAY_JOBS_API = (
    "https://{tenant}.{wd_server}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
)


class WorkdayFetcher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30.0)

    def fetch_jobs(self, board_token: str) -> list[RawJob]:
        tenant, wd_server, site = _parse_board_token(board_token)
        url = WORKDAY_JOBS_API.format(tenant=tenant, wd_server=wd_server, site=site)
        referer = f"https://{tenant}.{wd_server}.myworkdayjobs.com/en-US/{site}"

        jobs: list[RawJob] = []
        offset = 0
        limit = 20

        while True:
            response = self._client.post(
                url,
                json={
                    "appliedFacets": {},
                    "limit": limit,
                    "offset": offset,
                    "searchText": "",
                },
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Accept-Language": "en-US",
                    "Referer": referer,
                },
            )
            if response.status_code in {404, 422}:
                return jobs
            response.raise_for_status()
            data = response.json()

            postings = data.get("jobPostings", [])
            if not postings:
                break

            for posting in postings:
                external_path = posting.get("externalPath", "")
                apply_url = (
                    f"https://{tenant}.{wd_server}.myworkdayjobs.com/en-US{external_path}"
                    if external_path
                    else ""
                )

                jobs.append(
                    RawJob(
                        title=posting.get("title", ""),
                        location=posting.get("locationsText"),
                        department=None,
                        apply_url=apply_url,
                        posted_at=extract_posted_at("workday", posting),
                        raw_data=posting,
                    )
                )

            total = data.get("total", 0)
            offset += len(postings)
            if offset >= total:
                break

        return jobs


def _parse_board_token(board_token: str) -> tuple[str, str, str]:
    parts = board_token.split(":", 2)
    if len(parts) == 3 and parts[2]:
        return parts[0], parts[1], parts[2]
    if len(parts) >= 2:
        return parts[0], parts[1], ""
    return parts[0], "wd5", ""


def create_workday_fetcher(client: httpx.Client | None = None) -> Fetcher:
    return WorkdayFetcher(client)
