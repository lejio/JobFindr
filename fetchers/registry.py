import random
import time
from typing import TYPE_CHECKING

import httpx

from fetchers.ashby import AshbyFetcher
from fetchers.bamboohr import BamboohrFetcher
from fetchers.base import Fetcher
from fetchers.greenhouse import GreenhouseFetcher
from fetchers.icims import IcimsFetcher
from fetchers.job_descriptions import get_job_description
from fetchers.jobvite import JobviteFetcher
from fetchers.lever import LeverFetcher
from fetchers.rippling import RipplingFetcher
from fetchers.smartrecruiters import SmartRecruitersFetcher
from fetchers.successfactors import SuccessfactorsFetcher
from fetchers.taleo import TaleoFetcher
from fetchers.teamtailor import TeamtailorFetcher
from fetchers.workable import WorkableFetcher
from fetchers.workday import WorkdayFetcher
from fetchers.ats_types import AtsType, FETCHABLE_ATS
from models.job import RawJob

if TYPE_CHECKING:
    from agent.worker_client import WorkerClient

_FETCHER_FACTORIES: dict[str, type] = {
    "greenhouse": GreenhouseFetcher,
    "lever": LeverFetcher,
    "ashby": AshbyFetcher,
    "workable": WorkableFetcher,
    "teamtailor": TeamtailorFetcher,
    "workday": WorkdayFetcher,
    "icims": IcimsFetcher,
    "taleo": TaleoFetcher,
    "successfactors": SuccessfactorsFetcher,
    "smartrecruiters": SmartRecruitersFetcher,
    "jobvite": JobviteFetcher,
    "rippling": RipplingFetcher,
    "bamboohr": BamboohrFetcher,
}

_WORKER_AWARE_FETCHERS = frozenset({"jobvite", "icims"})


class FetcherRegistry:
    def __init__(
        self,
        client: httpx.Client | None = None,
        worker: "WorkerClient | None" = None,
        min_delay: float = 1.0,
        max_delay: float = 2.0,
    ):
        self._client = client or httpx.Client(timeout=30.0)
        self._worker = worker
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._fetchers: dict[str, Fetcher] = {}
        for ats, cls in _FETCHER_FACTORIES.items():
            if ats in _WORKER_AWARE_FETCHERS:
                self._fetchers[ats] = cls(self._client, worker=worker)
            else:
                self._fetchers[ats] = cls(self._client)

    def fetch_jobs(self, ats_type: AtsType, board_token: str) -> list[RawJob]:
        if ats_type not in FETCHABLE_ATS:
            raise ValueError(f"Job API fetch not implemented for ATS type: {ats_type}")
        fetcher = self._fetchers[ats_type]
        return fetcher.fetch_jobs(board_token)

    def fetch_description(
        self,
        ats_type: AtsType,
        board_token: str,
        raw_job: RawJob,
    ) -> str | None:
        return get_job_description(ats_type, board_token, raw_job, self._client)

    def rate_limit_pause(self) -> None:
        time.sleep(random.uniform(self._min_delay, self._max_delay))

    def close(self) -> None:
        self._client.close()
