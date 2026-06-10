import re
from urllib.parse import urlparse

from fetchers.ats_types import AtsType

GREENHOUSE_PATTERN = re.compile(
    r"(?:https?://)?(?:boards\.greenhouse\.io|job-boards\.greenhouse\.io)/([^/?#]+)",
    re.IGNORECASE,
)
LEVER_PATTERN = re.compile(
    r"(?:https?://)?jobs\.lever\.co/([^/?#]+)",
    re.IGNORECASE,
)
ASHBY_PATTERN = re.compile(
    r"(?:https?://)?jobs\.ashbyhq\.com/([^/?#]+)",
    re.IGNORECASE,
)
WORKABLE_PATTERN = re.compile(
    r"(?:https?://)?apply\.workable\.com/([^/?#]+)",
    re.IGNORECASE,
)
TEAMTAILOR_PATTERN = re.compile(
    r"(?:https?://)?([^.]+)\.teamtailor\.com",
    re.IGNORECASE,
)
WORKDAY_HOST_PATTERN = re.compile(
    r"(?:https?://)?([^.]+)\.wd\d+\.myworkdayjobs\.com",
    re.IGNORECASE,
)
ICIMS_PATTERN = re.compile(
    r"(?:https?://)?([^.]+)\.icims\.com",
    re.IGNORECASE,
)
TALEO_PATTERN = re.compile(
    r"(?:https?://)?([^.]+)\.taleo\.net/careersection/([^/?#]+)",
    re.IGNORECASE,
)
SMARTRECRUITERS_PATTERN = re.compile(
    r"(?:https?://)?jobs\.smartrecruiters\.com/([^/?#]+)",
    re.IGNORECASE,
)
JOBVITE_PATTERN = re.compile(
    r"(?:https?://)?jobs\.jobvite\.com/([^/?#]+)",
    re.IGNORECASE,
)
SAP_JOBS_PATTERN = re.compile(
    r"(?:https?://)?jobs\.sap\.com/([^/?#]+)",
    re.IGNORECASE,
)
JOBS2WEB_PATTERN = re.compile(
    r"(?:https?://)?([^.]+)\.jobs2web\.com",
    re.IGNORECASE,
)
RIPPLING_ATS_HOST_PATTERN = re.compile(
    r"(?:https?://)?ats\.rippling\.com/([^/?#]+)",
    re.IGNORECASE,
)
RIPPLING_ATS_PATTERN = re.compile(
    r"(?:https?://)?([^.]+)\.rippling-ats\.com",
    re.IGNORECASE,
)
RIPPLING_CAREERS_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?rippling\.com/careers",
    re.IGNORECASE,
)
BAMBOOHR_PATTERN = re.compile(
    r"(?:https?://)?([^.]+)\.bamboohr\.com/(?:careers|jobs)",
    re.IGNORECASE,
)


def detect_ats(url: str) -> tuple[AtsType, str, str] | None:
    """Detect ATS type and board token from a careers URL."""
    url = url.strip()
    if not url:
        return None

    for pattern, ats_type, canonical_prefix in (
        (GREENHOUSE_PATTERN, "greenhouse", "https://boards.greenhouse.io"),
        (LEVER_PATTERN, "lever", "https://jobs.lever.co"),
        (ASHBY_PATTERN, "ashby", "https://jobs.ashbyhq.com"),
        (WORKABLE_PATTERN, "workable", "https://apply.workable.com"),
        (SMARTRECRUITERS_PATTERN, "smartrecruiters", "https://jobs.smartrecruiters.com"),
        (JOBVITE_PATTERN, "jobvite", "https://jobs.jobvite.com"),
        (SAP_JOBS_PATTERN, "successfactors", "https://jobs.sap.com"),
    ):
        match = pattern.search(url)
        if match:
            token = match.group(1).lower()
            canonical_url = f"{canonical_prefix}/{token}"
            return ats_type, token, canonical_url

    match = TEAMTAILOR_PATTERN.search(url)
    if match:
        token = match.group(1).lower()
        return "teamtailor", token, f"https://{token}.teamtailor.com/jobs"

    match = WORKDAY_HOST_PATTERN.search(url)
    if match:
        return _detect_workday(url)

    match = ICIMS_PATTERN.search(url)
    if match:
        token = match.group(1).lower()
        return "icims", token, f"https://{token}.icims.com/jobs"

    match = TALEO_PATTERN.search(url)
    if match:
        host_token = match.group(1).lower()
        section = match.group(2).lower()
        board_token = f"{host_token}:{section}"
        return (
            "taleo",
            board_token,
            f"https://{host_token}.taleo.net/careersection/{section}/joblist.ftl",
        )

    match = JOBS2WEB_PATTERN.search(url)
    if match:
        token = match.group(1).lower()
        return "successfactors", token, f"https://{token}.jobs2web.com"

    match = RIPPLING_ATS_HOST_PATTERN.search(url)
    if match:
        token = match.group(1).lower()
        return "rippling", token, f"https://ats.rippling.com/{token}/jobs"

    match = RIPPLING_ATS_PATTERN.search(url)
    if match:
        token = match.group(1).lower()
        return "rippling", token, f"https://ats.rippling.com/{token}/jobs"

    if RIPPLING_CAREERS_PATTERN.search(url):
        return "rippling", "careers", "https://ats.rippling.com/careers/jobs"

    match = BAMBOOHR_PATTERN.search(url)
    if match:
        token = match.group(1).lower()
        parsed = urlparse(url if "://" in url else f"https://{url}")
        path = parsed.path.lower()
        section = "careers" if "/careers" in path else "jobs"
        return "bamboohr", token, f"https://{token}.bamboohr.com/{section}"

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path_parts = [p for p in parsed.path.split("/") if p]

    if "greenhouse.io" in host and path_parts:
        token = path_parts[0].lower()
        return "greenhouse", token, f"https://boards.greenhouse.io/{token}"

    if "lever.co" in host and path_parts:
        token = path_parts[0].lower()
        return "lever", token, f"https://jobs.lever.co/{token}"

    if "ashbyhq.com" in host and path_parts:
        token = path_parts[0].lower()
        return "ashby", token, f"https://jobs.ashbyhq.com/{token}"

    if "workable.com" in host and path_parts:
        token = path_parts[0].lower()
        return "workable", token, f"https://apply.workable.com/{token}"

    if "teamtailor.com" in host:
        subdomain = host.split(".")[0].lower()
        if subdomain not in {"www", "app"}:
            return "teamtailor", subdomain, f"https://{subdomain}.teamtailor.com/jobs"

    if "myworkdayjobs.com" in host:
        return _detect_workday(url if "://" in url else f"https://{url}")

    if "icims.com" in host:
        subdomain = host.split(".")[0].lower()
        return "icims", subdomain, f"https://{host}/jobs"

    if "smartrecruiters.com" in host and path_parts:
        token = path_parts[0].lower()
        return "smartrecruiters", token, f"https://jobs.smartrecruiters.com/{token}"

    if "jobvite.com" in host and path_parts:
        token = path_parts[0].lower()
        return "jobvite", token, f"https://jobs.jobvite.com/{token}"

    if host == "ats.rippling.com" and path_parts:
        token = path_parts[0].lower()
        return "rippling", token, f"https://ats.rippling.com/{token}/jobs"

    return None


def _detect_workday(url: str) -> tuple[AtsType, str, str]:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = parsed.netloc.lower()
    path_parts = [p for p in parsed.path.split("/") if p]

    tenant = host.split(".")[0].lower()
    wd_match = re.search(r"\.(wd\d+)\.myworkdayjobs\.com", host)
    wd_server = wd_match.group(1) if wd_match else "wd5"

    locale_prefixes = {"en-us", "en-gb", "fr-fr", "de-de", "es-es", "ja-jp", "zh-cn"}
    site_parts = path_parts
    if site_parts and site_parts[0].lower() in locale_prefixes:
        site_parts = site_parts[1:]

    site = site_parts[0] if site_parts else ""
    board_token = f"{tenant}:{wd_server}:{site}" if site else f"{tenant}:{wd_server}"

    base = f"https://{host}"
    if path_parts:
        canonical_url = (
            f"{base}/{'/'.join(path_parts[:2])}"
            if len(path_parts) >= 2
            else f"{base}/{path_parts[0]}"
        )
    else:
        canonical_url = base

    return "workday", board_token, canonical_url
