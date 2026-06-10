import threading
from dataclasses import dataclass, field

from models.usage import ProxyTrafficStats, TokenUsageStats


@dataclass
class TokenUsageTracker:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0

    def record(self, usage_metadata: object | None) -> None:
        if usage_metadata is None:
            self.api_calls += 1
            return

        prompt = getattr(usage_metadata, "prompt_token_count", None) or 0
        completion = getattr(usage_metadata, "candidates_token_count", None) or 0
        total = getattr(usage_metadata, "total_token_count", None) or (prompt + completion)

        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total
        self.api_calls += 1

    def to_stats(self) -> TokenUsageStats:
        return TokenUsageStats(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            api_calls=self.api_calls,
        )


@dataclass
class ProxyTrafficTracker:
    requests: int = 0
    bytes_downloaded: int = 0
    bytes_uploaded: int = 0
    search_calls: int = 0
    scrape_calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_search(self, traffic: dict | None) -> None:
        with self._lock:
            self.search_calls += 1
            self._absorb_unlocked(traffic)

    def record_scrape(self, traffic: dict | None) -> None:
        with self._lock:
            self.scrape_calls += 1
            self._absorb_unlocked(traffic)

    def absorb_worker_totals(self, worker_stats: dict | None) -> None:
        if not worker_stats:
            return
        with self._lock:
            self.requests = max(self.requests, int(worker_stats.get("requests", 0)))
            self.bytes_downloaded = max(
                self.bytes_downloaded, int(worker_stats.get("bytes_downloaded", 0))
            )
            self.bytes_uploaded = max(
                self.bytes_uploaded, int(worker_stats.get("bytes_uploaded", 0))
            )
            self.search_calls = max(self.search_calls, int(worker_stats.get("search_calls", 0)))
            self.scrape_calls = max(self.scrape_calls, int(worker_stats.get("scrape_calls", 0)))

    def _absorb(self, traffic: dict | None) -> None:
        with self._lock:
            self._absorb_unlocked(traffic)

    def _absorb_unlocked(self, traffic: dict | None) -> None:
        if not traffic:
            return
        self.requests += int(traffic.get("requests", 0))
        self.bytes_downloaded += int(traffic.get("bytes_downloaded", 0))
        self.bytes_uploaded += int(traffic.get("bytes_uploaded", 0))

    def to_stats(self) -> ProxyTrafficStats:
        return ProxyTrafficStats(
            requests=self.requests,
            bytes_downloaded=self.bytes_downloaded,
            bytes_uploaded=self.bytes_uploaded,
            search_calls=self.search_calls,
            scrape_calls=self.scrape_calls,
        )


def format_bytes(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"
