import re
import xml.etree.ElementTree as ET

import httpx

from fetchers.base import Fetcher
from fetchers.job_dates import extract_posted_at
from models.job import RawJob

TEAMTAILOR_RSS = "https://{token}.teamtailor.com/jobs.rss"


class TeamtailorFetcher:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30.0)

    def fetch_jobs(self, board_token: str) -> list[RawJob]:
        url = TEAMTAILOR_RSS.format(token=board_token)
        response = self._client.get(url, params={"per_page": 200})
        if response.status_code == 404:
            return []
        response.raise_for_status()

        root = ET.fromstring(response.text)
        channel = root.find("channel")
        if channel is None:
            return []

        jobs: list[RawJob] = []
        for item in channel.findall("item"):
            title = _text(item.find("title"))
            link = _text(item.find("link"))
            pub_date = _text(item.find("pubDate"))
            description = _text(item.find("description"))

            location = None
            department = None
            loc_el = item.find("{https://teamtailor.com/locations}location")
            if loc_el is not None:
                location = _text(loc_el)
            dept_el = item.find("{https://teamtailor.com/departments}department")
            if dept_el is not None:
                department = _text(dept_el)

            if not location:
                location_match = re.search(r"Location:\s*([^\n<]+)", description or "")
                if location_match:
                    location = location_match.group(1).strip()

            raw_data = {
                "title": title,
                "link": link,
                "pubDate": pub_date,
                "description": description,
                "location": location,
                "department": department,
            }

            jobs.append(
                RawJob(
                    title=title,
                    location=location,
                    department=department,
                    apply_url=link,
                    posted_at=extract_posted_at("teamtailor", raw_data),
                    raw_data=raw_data,
                )
            )

        return jobs


def _text(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def create_teamtailor_fetcher(client: httpx.Client | None = None) -> Fetcher:
    return TeamtailorFetcher(client)
