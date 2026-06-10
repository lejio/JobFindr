import html
import re
from urllib.parse import urljoin, urlparse

from fetchers.ats_types import AtsType
from models.job import RawJob

LOCALE_TITLE_BLOCKLIST = frozenset(
    {
        "deutsch (deutschland)",
        "english (global)",
        "français (france)",
        "日本語 (日本)",
        "简体中文 (中国大陆)",
        "español",
        "português",
        "italiano",
        "nederlands",
    }
)


def html_to_text(text: str) -> str:
    cleaned = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<style[^>]*>.*?</style>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def filter_job_link(ats_type: AtsType | None, apply_url: str, title: str) -> bool:
    if not apply_url or not title:
        return False

    lower_url = apply_url.lower()
    lower_title = title.lower().strip()

    if lower_title in LOCALE_TITLE_BLOCKLIST:
        return False
    if "read story" in lower_title or lower_title.endswith(" story"):
        return False

    if ats_type == "successfactors":
        return _is_successfactors_job_link(lower_url, lower_title)
    if ats_type == "rippling":
        return _is_rippling_job_link(lower_url, lower_title)
    if ats_type == "jobvite":
        return "/job/" in lower_url and "jobvite.com" in lower_url
    if ats_type == "icims":
        return bool(re.search(r"icims\.com/jobs/\d+", lower_url))

    return True


def _is_successfactors_job_link(lower_url: str, lower_title: str) -> bool:
    if "mailto:" in lower_url:
        return False
    if "locale=" in lower_url:
        return False
    if any(part in lower_url for part in ("/search", "/topjobs", "/content/", "/privacy")):
        return False

    if "jobs.sap.com" in lower_url:
        return bool(re.search(r"/job/[^/]+/\d+/?", lower_url))

    if "jobs2web.com" in lower_url:
        return bool(re.search(r"/(job|go)/[^/]+/\d+/?", lower_url))

    return False


def _is_rippling_job_link(lower_url: str, lower_title: str) -> bool:
    if any(
        part in lower_url
        for part in (
            "/blog",
            "/story",
            "/customers",
            "/news",
            "/resources",
            "linkedin.com",
            "twitter.com",
            "x.com",
        )
    ):
        return False

    if "rippling-ats.com" in lower_url:
        return "/job/" in lower_url or "/jobs/" in lower_url

    if "rippling.com" in lower_url:
        if "/careers/open-roles/" in lower_url:
            return True
        if re.search(r"/careers/[^/]+/[^/]+", lower_url):
            return True
        if "/careers/" in lower_url and lower_url.rstrip("/").endswith("/careers"):
            return False
        return "/careers/" in lower_url and len(urlparse(lower_url).path.strip("/").split("/")) >= 2

    return False


def extract_anchor_jobs(
    page_html: str,
    base_url: str,
    *,
    href_pattern: str,
    min_title_len: int = 3,
    ats_type: AtsType | None = None,
) -> list[RawJob]:
    jobs: list[RawJob] = []
    seen_urls: set[str] = set()
    pattern = re.compile(
        rf'<a[^>]+href=["\']({href_pattern})["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )

    for match in pattern.finditer(page_html):
        href = html.unescape(match.group(1)).strip()
        title = html_to_text(match.group(2))
        if len(title) < min_title_len:
            continue

        apply_url = urljoin(base_url, href)
        if apply_url in seen_urls:
            continue
        if not filter_job_link(ats_type, apply_url, title):
            continue

        seen_urls.add(apply_url)
        jobs.append(
            RawJob(
                title=title,
                location=None,
                department=None,
                apply_url=apply_url,
                posted_at=None,
                raw_data={"title": title, "apply_url": apply_url},
            )
        )

    return jobs
