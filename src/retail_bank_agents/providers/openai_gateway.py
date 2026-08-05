from time import monotonic
from typing import TypeVar

import structlog
from openai import APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from retail_bank_agents.config import Settings
from retail_bank_agents.metrics import PROVIDER_LATENCY

T = TypeVar("T", bound=BaseModel)
logger = structlog.get_logger(__name__)


class OpenAIResponsesGateway:
    """OpenAI Responses API adapter with structured outputs and privacy-safe defaults."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.request_timeout_seconds,
            max_retries=0,
        )

    @retry(
        retry=retry_if_exception_type((RateLimitError, APITimeoutError)),
        wait=wait_random_exponential(multiplier=0.5, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def parse(
        self,
        *,
        instructions: str,
        user_input: str,
        output_type: type[T],
        safety_identifier: str,
    ) -> T:
        started = monotonic()
        try:
            response = await self._client.responses.parse(
                model=self._settings.openai_model,
                instructions=instructions,
                input=user_input,
                text_format=output_type,
                reasoning={"effort": self._settings.openai_reasoning_effort},
                safety_identifier=safety_identifier,
                store=False,
            )
            parsed = response.output_parsed
            if parsed is None:
                raise ValueError("model returned no structured output")
            return parsed
        finally:
            PROVIDER_LATENCY.labels(provider="openai", operation="parse").observe(
                monotonic() - started
            )

    @retry(
        retry=retry_if_exception_type((RateLimitError, APITimeoutError)),
        wait=wait_random_exponential(multiplier=0.5, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def generate(
        self,
        *,
        instructions: str,
        user_input: str,
        safety_identifier: str,
    ) -> str:
        started = monotonic()
        try:
            response = await self._client.responses.create(
                model=self._settings.openai_model,
                instructions=instructions,
                input=user_input,
                reasoning={"effort": self._settings.openai_reasoning_effort},
                safety_identifier=safety_identifier,
                store=False,
                max_output_tokens=1_200,
            )
            if not response.output_text:
                raise ValueError("model returned an empty response")
            return response.output_text
        finally:
            PROVIDER_LATENCY.labels(provider="openai", operation="generate").observe(
                monotonic() - started
            )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        started = monotonic()
        try:
            response = await self._client.embeddings.create(
                model=self._settings.openai_embedding_model,
                input=texts,
                encoding_format="float",
            )
            return [item.embedding for item in response.data]
        finally:
            PROVIDER_LATENCY.labels(provider="openai", operation="embed").observe(
                monotonic() - started
            )
