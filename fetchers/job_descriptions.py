import html
import logging
import re
import httpx

from fetchers.ats_types import AtsType
from models.job import RawJob

logger = logging.getLogger(__name__)

GREENHOUSE_JOB_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}"
MAX_DESCRIPTION_CHARS = 10_000


def get_job_description(
    ats_type: AtsType,
    board_token: str,
    raw_job: RawJob,
    client: httpx.Client | None = None,
) -> str | None:
    if ats_type == "ashby":
        return _from_ashby(raw_job)
    if ats_type == "lever":
        return _from_lever(raw_job)
    if ats_type == "greenhouse":
        return _from_greenhouse(board_token, raw_job, client)
    if ats_type == "workable":
        return _from_workable(raw_job)
    if ats_type == "smartrecruiters":
        return _from_smartrecruiters(board_token, raw_job, client)
    if ats_type == "teamtailor":
        return _from_teamtailor(raw_job)
    return None


def _from_ashby(raw_job: RawJob) -> str | None:
    plain = raw_job.raw_data.get("descriptionPlain")
    if plain:
        return _truncate(plain)
    html_desc = raw_job.raw_data.get("descriptionHtml")
    if html_desc:
        return _truncate(_html_to_text(html_desc))
    return None


def _from_lever(raw_job: RawJob) -> str | None:
    plain = raw_job.raw_data.get("descriptionPlain")
    if plain:
        return _truncate(plain)
    html_desc = raw_job.raw_data.get("description")
    if html_desc:
        return _truncate(_html_to_text(html_desc))
    return None


def _from_greenhouse(
    board_token: str,
    raw_job: RawJob,
    client: httpx.Client | None,
) -> str | None:
    job_id = raw_job.raw_data.get("id")
    if not job_id:
        return None

    content = raw_job.raw_data.get("content")
    if content:
        return _truncate(_html_to_text(html.unescape(str(content))))

    http = client or httpx.Client(timeout=30.0)
    owns_client = client is None

    try:
        url = GREENHOUSE_JOB_API.format(token=board_token, job_id=job_id)
        response = http.get(url)
        response.raise_for_status()
        data = response.json()
        content = data.get("content")
        if content:
            return _truncate(_html_to_text(html.unescape(str(content))))
    except httpx.HTTPError as exc:
        logger.warning(
            "Failed to fetch Greenhouse job description for id %s: %s",
            job_id,
            exc,
        )
    finally:
        if owns_client:
            http.close()

    return None


def _from_workable(raw_job: RawJob) -> str | None:
    html_desc = raw_job.raw_data.get("description")
    if html_desc:
        return _truncate(_html_to_text(html.unescape(str(html_desc))))
    return None


def _from_smartrecruiters(
    board_token: str,
    raw_job: RawJob,
    client: httpx.Client | None,
) -> str | None:
    posting_id = raw_job.raw_data.get("id")
    if not posting_id:
        return None

    http = client or httpx.Client(timeout=30.0)
    owns_client = client is None

    try:
        url = (
            f"https://api.smartrecruiters.com/v1/companies/"
            f"{board_token}/postings/{posting_id}"
        )
        response = http.get(url)
        response.raise_for_status()
        data = response.json()
        job_ad = data.get("jobAd") or {}
        sections = job_ad.get("sections") or {}
        parts = []
        for key in ("jobDescription", "qualifications", "additionalInformation"):
            section = sections.get(key) or {}
            text = section.get("text")
            if text:
                parts.append(_html_to_text(str(text)))
        if parts:
            return _truncate("\n\n".join(parts))
    except httpx.HTTPError as exc:
        logger.warning(
            "Failed to fetch SmartRecruiters description for %s: %s",
            posting_id,
            exc,
        )
    finally:
        if owns_client:
            http.close()

    return None


def _from_teamtailor(raw_job: RawJob) -> str | None:
    description = raw_job.raw_data.get("description")
    if description:
        return _truncate(_html_to_text(str(description)))
    return None


def _html_to_text(text: str) -> str:
    cleaned = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<style[^>]*>.*?</style>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _truncate(text: str) -> str:
    if len(text) <= MAX_DESCRIPTION_CHARS:
        return text
    return text[:MAX_DESCRIPTION_CHARS]
