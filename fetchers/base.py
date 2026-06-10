from typing import Protocol

from models.job import RawJob


class Fetcher(Protocol):
    def fetch_jobs(self, board_token: str) -> list[RawJob]:
        """Fetch job postings for a given ATS board token."""
        ...
