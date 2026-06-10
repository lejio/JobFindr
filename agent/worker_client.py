import logging

import httpx

from agent.usage_tracker import ProxyTrafficTracker
from config import AppSettings

logger = logging.getLogger(__name__)


class WorkerClient:
    def __init__(self, settings: AppSettings, client: httpx.Client | None = None):
        self._settings = settings
        self._client = client or httpx.Client(
            base_url=settings.worker_url,
            timeout=settings.worker_timeout,
        )
        self.traffic = ProxyTrafficTracker()

    def health_check(self) -> bool:
        try:
            response = self._client.get("/health")
            response.raise_for_status()
            return response.json().get("status") == "ok"
        except httpx.HTTPError as exc:
            logger.warning("Worker health check failed: %s", exc)
            return False

    def get_metrics(self) -> dict:
        try:
            response = self._client.get("/metrics")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            logger.warning("Worker metrics fetch failed: %s", exc)
            return {}

    def google_search(self, query: str, max_results: int = 5) -> list[str]:
        response = self._client.post(
            "/search",
            json={"query": query, "max_results": max_results},
        )
        response.raise_for_status()
        data = response.json()

        self.traffic.record_search(data.get("traffic"))

        if data.get("blocked"):
            logger.warning(
                "Google blocked search for %r (proxy_enabled=%s). "
                "Configure DECODO_* or PROXY_URL in .env.",
                query,
                data.get("proxy_enabled"),
            )

        return data.get("urls", [])

    def scrape(
        self,
        url: str,
        capture_network: bool = True,
        *,
        scrape_options: dict | None = None,
    ) -> dict:
        payload: dict = {"url": url, "capture_network": capture_network}
        if scrape_options:
            payload.update(scrape_options)
        response = self._client.post("/scrape", json=payload)
        response.raise_for_status()
        data = response.json()
        self.traffic.record_scrape(data.get("traffic"))
        return data

    def close(self) -> None:
        self.traffic.absorb_worker_totals(self.get_metrics())
        self._client.close()
