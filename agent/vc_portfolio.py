import json
import logging
import re
import time
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from agent.gemini_client import GeminiClient
from agent.vc_registry import VCFirm, select_vcs_for_location
from agent.worker_client import WorkerClient
from config import SearchConfig
from models.portfolio import PortfolioCompany, TargetCompaniesStore

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
TARGET_COMPANIES_PATH = DATA_DIR / "target_companies.json"

YC_API = "https://api.ycombinator.com/v0.1/companies"


class ExtractedCompany(BaseModel):
    name: str
    website: str | None = None
    location_hint: str | None = None


class PortfolioExtractionResult(BaseModel):
    companies: list[ExtractedCompany] = Field(default_factory=list)


class VCPortfolioDiscovery:
    def __init__(self, gemini: GeminiClient, worker: WorkerClient | None = None):
        self._gemini = gemini
        self._worker = worker
        self._http = httpx.Client(timeout=45.0, follow_redirects=True)

    def discover(self, config: SearchConfig) -> list[PortfolioCompany]:
        firms = select_vcs_for_location(config.location, max_firms=config.max_vc_firms)
        logger.info(
            "Selected %d VC firms for location %r: %s",
            len(firms),
            config.location,
            ", ".join(f.name for f in firms),
        )

        all_companies: list[PortfolioCompany] = []
        seen_names: set[str] = set()

        for firm in firms:
            try:
                extracted = self._fetch_portfolio(firm, config)
                for company in extracted:
                    key = company.name.lower().strip()
                    if not key or key in seen_names:
                        continue
                    seen_names.add(key)
                    all_companies.append(company)
                logger.info("Extracted %d companies from %s", len(extracted), firm.name)
            except Exception as exc:
                logger.warning("Failed to fetch portfolio for %s: %s", firm.name, exc)

            time.sleep(1.0)

        store = TargetCompaniesStore(
            search_location=config.location,
            vc_firms_used=[f.name for f in firms],
            companies=all_companies,
        )
        self._save_target_companies(store)

        return all_companies

    def _fetch_portfolio(self, firm: VCFirm, config: SearchConfig) -> list[PortfolioCompany]:
        if firm.source == "yc_api":
            return self._fetch_yc_companies(firm.name, config)

        html = self._fetch_html(firm.portfolio_url)
        if not html:
            return []

        return self._extract_companies_from_html(
            html=html,
            vc_name=firm.name,
            location=config.location,
        )

    def _fetch_yc_companies(self, vc_name: str, config: SearchConfig) -> list[PortfolioCompany]:
        location_keywords = _location_match_terms(config.location)
        companies: list[PortfolioCompany] = []
        page = 1
        empty_streak = 0

        while page <= 80 and empty_streak < 3:
            response = self._http.get(YC_API, params={"page": page})
            response.raise_for_status()
            batch = response.json().get("companies", [])
            if not batch:
                break

            page_matches = 0
            for item in batch:
                if not _yc_matches_location(item, location_keywords):
                    continue

                if config.require_hiring and "isHiring" not in item.get("badges", []):
                    continue

                name = item.get("name", "").strip()
                if not name:
                    continue

                page_matches += 1
                companies.append(
                    PortfolioCompany(
                        name=name,
                        website=item.get("website"),
                        source_vc=vc_name,
                        location_hint=_format_yc_location(item),
                    )
                )

            if page_matches == 0:
                empty_streak += 1
            else:
                empty_streak = 0

            page += 1

        return companies

    def _fetch_html(self, url: str) -> str:
        try:
            response = self._http.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:
            logger.warning("HTTP fetch failed for %s: %s", url, exc)

        if not self._worker:
            return ""

        try:
            result = self._worker.scrape(url, capture_network=False)
            return result.get("html", "")
        except Exception as exc:
            logger.warning("Worker scrape failed for %s: %s", url, exc)
            return ""

    def _extract_companies_from_html(
        self,
        html: str,
        vc_name: str,
        location: str,
    ) -> list[PortfolioCompany]:
        text = _html_to_text(html)
        if len(text) < 200:
            return _extract_links_fallback(html, vc_name)

        prompt = (
            f"Extract portfolio companies from this VC portfolio page.\n\n"
            f"VC firm: {vc_name}\n"
            f"Target search location: {location}\n\n"
            f"Page text:\n{text}\n\n"
            "Return startup/company names and their website URLs when visible. "
            "Prefer companies with a presence in or relevance to the target location. "
            "Skip the VC firm itself, LPs, and generic navigation links."
        )

        try:
            result = self._gemini.generate_structured(
                prompt=prompt,
                schema=PortfolioExtractionResult,
                system_instruction=(
                    "Extract only real portfolio companies from venture capital portfolio pages. "
                    "Include company name and website when available."
                ),
            )
        except Exception as exc:
            logger.warning("Gemini portfolio extraction failed for %s: %s", vc_name, exc)
            return _extract_links_fallback(html, vc_name)

        return [
            PortfolioCompany(
                name=c.name,
                website=c.website,
                source_vc=vc_name,
                location_hint=c.location_hint,
            )
            for c in result.companies
            if c.name.strip()
        ]

    def _save_target_companies(self, store: TargetCompaniesStore) -> Path:
        DATA_DIR.mkdir(exist_ok=True)
        with TARGET_COMPANIES_PATH.open("w", encoding="utf-8") as f:
            json.dump(store.model_dump(mode="json"), f, indent=2)
        logger.info(
            "Saved %d target companies to %s",
            len(store.companies),
            TARGET_COMPANIES_PATH,
        )
        return TARGET_COMPANIES_PATH

    @staticmethod
    def load_target_companies() -> TargetCompaniesStore | None:
        if not TARGET_COMPANIES_PATH.exists():
            return None
        with TARGET_COMPANIES_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return TargetCompaniesStore.model_validate(data)

    def close(self) -> None:
        self._http.close()


def _html_to_text(html: str, max_len: int = 35000) -> str:
    cleaned = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<style[^>]*>.*?</style>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_len]


def _extract_links_fallback(html: str, vc_name: str) -> list[PortfolioCompany]:
    links = re.findall(r'href=["\'](https?://[^"\']+)["\']', html, flags=re.IGNORECASE)
    skip_domains = (
        "linkedin.com",
        "twitter.com",
        "x.com",
        "facebook.com",
        "instagram.com",
        "youtube.com",
        "medium.com",
        "google.com",
        "apple.com",
        "mailto:",
    )
    companies: list[PortfolioCompany] = []
    seen: set[str] = set()

    for link in links:
        lower = link.lower()
        if any(s in lower for s in skip_domains):
            continue
        domain = re.sub(r"^https?://(www\.)?", "", lower).split("/")[0]
        if domain in seen or len(domain) < 4:
            continue
        seen.add(domain)
        name = domain.split(".")[0].replace("-", " ").title()
        companies.append(
            PortfolioCompany(name=name, website=link, source_vc=vc_name)
        )

    return companies[:80]


def _location_match_terms(location: str) -> list[str]:
    loc = location.lower()
    terms = [loc, "new york", "nyc", "manhattan", "brooklyn"]
    if "austin" in loc:
        terms.extend(["austin", "texas"])
    if "san francisco" in loc or "bay area" in loc:
        terms.extend(["san francisco", "bay area", "sf"])
    return list(dict.fromkeys(terms))


def _yc_matches_location(item: dict, terms: list[str]) -> bool:
    locations = " ".join(item.get("locations") or []).lower()
    regions = " ".join(item.get("regions") or []).lower()
    combined = f"{locations} {regions}"
    return any(term in combined for term in terms)


def _format_yc_location(item: dict) -> str | None:
    locations = item.get("locations") or []
    if locations:
        return ", ".join(locations)
    regions = item.get("regions") or []
    if regions:
        return ", ".join(regions)
    return None
