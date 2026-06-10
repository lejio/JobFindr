import json
import logging
from contextlib import contextmanager
from typing import Generator, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from agent.resume_cache import (
    CACHED_RESUME_SYSTEM_INSTRUCTION,
    build_resume_cache_contents,
)
from agent.usage_tracker import TokenUsageTracker
from config import AppSettings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

DEFAULT_RESUME_CACHE_TTL = "3600s"


class GeminiClient:
    def __init__(self, settings: AppSettings):
        self._settings = settings
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self.usage = TokenUsageTracker()

    def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_instruction: str | None = None,
        *,
        cached_content: str | None = None,
    ) -> T:
        config_kwargs: dict = {
            "response_mime_type": "application/json",
            "response_schema": schema,
            "temperature": 0.2,
        }
        if cached_content:
            config_kwargs["cached_content"] = cached_content
        elif system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        response = self._client.models.generate_content(
            model=self._settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )

        self.usage.record(getattr(response, "usage_metadata", None))

        text = response.text or ""
        if not text.strip():
            raise ValueError("Gemini returned an empty response")

        try:
            return schema.model_validate_json(text)
        except Exception:
            data = json.loads(text)
            return schema.model_validate(data)

    def create_resume_cache(
        self,
        resume_text: str,
        *,
        ttl: str = DEFAULT_RESUME_CACHE_TTL,
    ) -> str | None:
        try:
            cached = self._client.caches.create(
                model=self._settings.gemini_model,
                config=types.CreateCachedContentConfig(
                    contents=build_resume_cache_contents(resume_text),
                    system_instruction=CACHED_RESUME_SYSTEM_INSTRUCTION,
                    display_name="jobfindr-resume",
                    ttl=ttl,
                ),
            )
            cache_name = cached.name
            if not cache_name:
                return None

            usage = getattr(cached, "usage_metadata", None)
            token_count = getattr(usage, "total_token_count", None)
            logger.info(
                "Created Gemini resume cache %s (%s tokens, ttl=%s)",
                cache_name,
                token_count if token_count is not None else "unknown",
                ttl,
            )
            return cache_name
        except Exception as exc:
            logger.info(
                "Resume context cache unavailable, falling back to inline resume: %s",
                exc,
            )
            return None

    def delete_resume_cache(self, cache_name: str | None) -> None:
        if not cache_name:
            return
        try:
            self._client.caches.delete(name=cache_name)
            logger.info("Deleted Gemini resume cache %s", cache_name)
        except Exception as exc:
            logger.warning("Failed to delete resume cache %s: %s", cache_name, exc)

    @contextmanager
    def resume_cache_session(
        self,
        resume_text: str,
        *,
        ttl: str = DEFAULT_RESUME_CACHE_TTL,
    ) -> Generator[str | None, None, None]:
        cache_name = self.create_resume_cache(resume_text, ttl=ttl)
        try:
            yield cache_name
        finally:
            self.delete_resume_cache(cache_name)
