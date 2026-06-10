import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import httpx

from fetchers.ats_detector import detect_ats
from fetchers.ats_types import AtsType
from models.job import CompanyTarget

logger = logging.getLogger(__name__)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
LEVER_API = "https://api.lever.co/v0/postings/{company}?mode=json"
ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{org}"
WORKABLE_API = "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"
SMARTRECRUITERS_API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1"
BAMBOOHR_API = "https://{slug}.bamboohr.com/careers/list"
RIPPLING_API = "https://ats.rippling.com/api/v2/board/{slug}/jobs?page=0&pageSize=1"
JOBVITE_PROBE_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}
CAREERS_PAGE_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}

CAREERS_PATHS = ("/careers", "/jobs", "/join-us", "/company/careers", "/about/careers")

ATS_PROBE_PRIORITY: tuple[AtsType, ...] = (
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "smartrecruiters",
    "rippling",
    "bamboohr",
    "jobvite",
)

ATS_URL_PATTERN = re.compile(
    r"https?://(?:boards\.greenhouse\.io|job-boards\.greenhouse\.io|jobs\.lever\.co|"
    r"jobs\.ashbyhq\.com|apply\.workable\.com|[^/\s]+\.teamtailor\.com|"
    r"[^/\s]+\.wd\d+\.myworkdayjobs\.com|[^/\s]+\.icims\.com|[^/\s]+\.taleo\.net|"
    r"jobs\.sap\.com|[^/\s]+\.jobs2web\.com|jobs\.smartrecruiters\.com|jobs\.jobvite\.com|"
    r"ats\.rippling\.com|[^/\s]+\.bamboohr\.com)[^\s\"'<>]*",
    re.IGNORECASE,
)

COMPANY_SUFFIXES = frozenset({"inc", "labs", "ai", "io", "co", "hq", "app", "tech"})


def company_slugs(name: str, website: str | None = None) -> list[str]:
    cleaned = re.sub(r"[^a-zA-Z0-9\s-]", "", name).strip().lower()
    compact = cleaned.replace(" ", "")
    hyphenated = cleaned.replace(" ", "-")
    underscored = cleaned.replace(" ", "_")

    slugs: list[str] = []
    for slug in (compact, hyphenated, underscored):
        if slug and slug not in slugs:
            slugs.append(slug)

    domain_slug = _slug_from_website(website)
    if domain_slug and domain_slug not in slugs:
        slugs.append(domain_slug)

    for slug in list(slugs):
        stripped = _strip_company_suffix(slug)
        if stripped and stripped not in slugs:
            slugs.append(stripped)

    return slugs


def _slug_from_website(website: str | None) -> str | None:
    if not website:
        return None

    parsed = urlparse(website if "://" in website else f"https://{website}")
    host = parsed.netloc.lower().removeprefix("www.")
    if not host or "." not in host:
        return None

    stem = host.split(".")[0]
    return stem if stem and stem not in {"www", "app", "careers", "jobs"} else None


def _strip_company_suffix(slug: str) -> str | None:
    for sep in ("-", "_"):
        if sep in slug:
            parts = slug.split(sep)
            if parts[-1] in COMPANY_SUFFIXES:
                trimmed = sep.join(parts[:-1])
                return trimmed or None
    if slug.endswith("inc") and len(slug) > 3:
        return slug[:-3].rstrip("-_") or None
    return None


def probe_careers_page(
    website: str,
    client: httpx.Client,
) -> tuple[AtsType, str, str] | None:
    base = website.strip()
    if not base:
        return None
    if "://" not in base:
        base = f"https://{base}"

    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    for path in CAREERS_PATHS:
        url = urljoin(origin + "/", path.lstrip("/"))
        try:
            response = client.get(url, headers=CAREERS_PAGE_HEADERS, follow_redirects=True)
        except httpx.HTTPError:
            continue

        if response.status_code >= 400:
            continue

        detected = _detect_ats_in_html(response.text)
        if detected:
            logger.info("ATS found on careers page %s", response.url)
            return detected

    return None


def _detect_ats_in_html(html: str) -> tuple[AtsType, str, str] | None:
    seen: set[str] = set()
    for match in ATS_URL_PATTERN.finditer(html):
        candidate = match.group(0).rstrip(".,;)")
        if candidate in seen:
            continue
        seen.add(candidate)

        detected = detect_ats(candidate)
        if detected:
            return detected

    return None


def _probe_definitions(slug: str) -> list[tuple[AtsType, str, str]]:
    return [
        ("greenhouse", GREENHOUSE_API.format(token=slug), f"https://boards.greenhouse.io/{slug}"),
        ("lever", LEVER_API.format(company=slug), f"https://jobs.lever.co/{slug}"),
        ("ashby", ASHBY_API.format(org=slug), f"https://jobs.ashbyhq.com/{slug}"),
        ("workable", WORKABLE_API.format(slug=slug), f"https://apply.workable.com/{slug}"),
        (
            "smartrecruiters",
            SMARTRECRUITERS_API.format(slug=slug),
            f"https://jobs.smartrecruiters.com/{slug}",
        ),
        ("bamboohr", BAMBOOHR_API.format(slug=slug), f"https://{slug}.bamboohr.com/careers"),
        ("rippling", RIPPLING_API.format(slug=slug), f"https://ats.rippling.com/{slug}/jobs"),
        ("jobvite", f"https://jobs.jobvite.com/{slug}/jobs", f"https://jobs.jobvite.com/{slug}/jobs"),
    ]


def _probe_single(
    ats_type: AtsType,
    api_url: str,
    careers_url: str,
    http: httpx.Client,
) -> CompanyTarget | None:
    try:
        if ats_type == "jobvite":
            response = http.get(api_url, headers=JOBVITE_PROBE_HEADERS)
            if response.status_code != 200:
                return None
            if "invalid=1" in str(response.url).lower():
                return None
            if "/job/" not in response.text:
                return None
        else:
            response = http.get(api_url)
            if response.status_code != 200:
                return None

            data = response.json()
            if not _has_jobs(ats_type, data):
                return None

        detected = detect_ats(careers_url)
        if not detected:
            return None

        detected_type, board_token, canonical_url = detected
        return CompanyTarget(
            name="",
            ats_type=detected_type,
            board_token=board_token,
            careers_url=canonical_url,
        )
    except (httpx.HTTPError, ValueError):
        return None


def _has_jobs(ats_type: AtsType, data: object) -> bool:
    if ats_type == "greenhouse":
        return bool(isinstance(data, dict) and data.get("jobs"))
    if ats_type == "lever":
        return isinstance(data, list) and len(data) > 0
    if ats_type == "ashby":
        return bool(isinstance(data, dict) and data.get("jobs"))
    if ats_type == "workable":
        return bool(isinstance(data, dict) and data.get("jobs"))
    if ats_type == "smartrecruiters":
        return bool(isinstance(data, dict) and data.get("content"))
    if ats_type == "bamboohr":
        return bool(isinstance(data, dict) and data.get("result"))
    if ats_type == "rippling":
        return bool(isinstance(data, dict) and data.get("items"))
    return False


def _probe_slug(slug: str, http: httpx.Client) -> CompanyTarget | None:
    probes = _probe_definitions(slug)
    results: dict[AtsType, CompanyTarget] = {}

    with ThreadPoolExecutor(max_workers=len(probes)) as executor:
        futures = {
            executor.submit(_probe_single, ats_type, api_url, careers_url, http): ats_type
            for ats_type, api_url, careers_url in probes
        }
        for future in as_completed(futures):
            ats_type = futures[future]
            try:
                target = future.result()
            except Exception:
                continue
            if target:
                results[ats_type] = target

    for ats_type in ATS_PROBE_PRIORITY:
        if ats_type in results:
            return results[ats_type]

    return None


def probe_ats_board(
    company_name: str,
    website: str | None = None,
    client: httpx.Client | None = None,
) -> CompanyTarget | None:
    """Try common ATS URL slugs via fast HTTP/API probes."""
    http = client or httpx.Client(timeout=15.0)
    owns_client = client is None

    try:
        for slug in company_slugs(company_name, website):
            target = _probe_slug(slug, http)
            if target:
                target.name = company_name
                logger.info(
                    "ATS probe matched %s via %s slug '%s'",
                    company_name,
                    target.ats_type,
                    slug,
                )
                return target
    finally:
        if owns_client:
            http.close()

    return None


def resolve_company_ats(
    company_name: str,
    website: str | None = None,
    client: httpx.Client | None = None,
) -> CompanyTarget | None:
    """Resolve ATS using cheap HTTP probes before any browser search."""
    http = client or httpx.Client(timeout=15.0)
    owns_client = client is None

    try:
        if website:
            detected = detect_ats(website)
            if detected:
                detected_type, board_token, canonical_url = detected
                return CompanyTarget(
                    name=company_name,
                    ats_type=detected_type,
                    board_token=board_token,
                    careers_url=canonical_url,
                )

            careers_detected = probe_careers_page(website, http)
            if careers_detected:
                detected_type, board_token, canonical_url = careers_detected
                return CompanyTarget(
                    name=company_name,
                    ats_type=detected_type,
                    board_token=board_token,
                    careers_url=canonical_url,
                )

        probed = probe_ats_board(company_name, website=website, client=http)
        if probed:
            return probed
    finally:
        if owns_client:
            http.close()

    return None
