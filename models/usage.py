from pydantic import BaseModel, Field


class TokenUsageStats(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0


class ProxyTrafficStats(BaseModel):
    requests: int = 0
    bytes_downloaded: int = 0
    bytes_uploaded: int = 0
    search_calls: int = 0
    scrape_calls: int = 0


class UsageStats(BaseModel):
    tokens: TokenUsageStats = Field(default_factory=TokenUsageStats)
    proxy: ProxyTrafficStats = Field(default_factory=ProxyTrafficStats)
