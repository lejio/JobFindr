from dataclasses import dataclass, field
import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from models.job import CompanyTarget

load_dotenv()


@dataclass
class SearchConfig:
    role: str
    location: str
    company_profile: str
    experience: str = ""
    posted_within_days: int | None = 30
    max_companies: int = 15
    include_remote: bool = True
    use_vc_discovery: bool = True
    max_vc_firms: int = 12
    require_hiring: bool = False
    direct_targets: list["CompanyTarget"] | None = field(default=None)
    resume_path: str = "resume.txt"
    resume_deep_threshold: int = 25
    resume_enabled: bool = True
    fetch_concurrency: int = 5


@dataclass
class AppSettings:
    gemini_api_key: str
    gemini_model: str
    worker_url: str
    worker_timeout: float


def load_settings() -> AppSettings:
    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_api_key:
        raise ValueError("GEMINI_API_KEY is required in .env")

    worker_host = os.getenv("WORKER_HOST", "127.0.0.1")
    worker_port = os.getenv("WORKER_PORT", "3847")
    worker_url = os.getenv("WORKER_URL", f"http://{worker_host}:{worker_port}")

    return AppSettings(
        gemini_api_key=gemini_api_key,
        gemini_model=os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.5-flash"),
        worker_url=worker_url.rstrip("/"),
        worker_timeout=float(os.getenv("WORKER_TIMEOUT", "120")),
    )


# Edit these values before each run (mirrors a future POST /search payload).
#
# Direct-target test mode (skips Gemini + stealth search discovery):
#   from models.job import CompanyTarget
#   direct_targets=[
#       CompanyTarget(
#           name="Stripe",
#           ats_type="greenhouse",
#           board_token="stripe",
#           careers_url="https://boards.greenhouse.io/stripe",
#       ),
#   ],
DEFAULT_SEARCH_CONFIG = SearchConfig(
    role="Software Engineer",
    location="New York City, NY",
    company_profile="Series A–C tech startups using Greenhouse, Lever, or Ashby",
    experience="Entry level (New Grad)",
    posted_within_days=7,
    max_companies=20,
    include_remote=True,
    use_vc_discovery=True,
    max_vc_firms=12,
    require_hiring=False,
    fetch_concurrency=int(os.getenv("FETCH_CONCURRENCY", "5")),
)
