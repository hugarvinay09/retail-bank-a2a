from time import monotonic

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from retail_bank_agents.config import Settings
from retail_bank_agents.domain.models import (
    AccountSummary,
    Beneficiary,
    PaymentDraft,
    PaymentExecution,
)
from retail_bank_agents.metrics import PROVIDER_LATENCY


class BankAPI:
    """Anti-corruption layer for the bank's canonical APIs; no model sees API credentials."""

    def __init__(self, settings: Settings) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.bank_api_base_url,
            headers={"Authorization": f"Bearer {settings.bank_api_token.get_secret_value()}"},
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout)),
        wait=wait_exponential_jitter(initial=0.2, max=2),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def get_account(self, customer_id: str, account_id: str) -> AccountSummary:
        started = monotonic()
        try:
            response = await self._client.get(f"/v1/customers/{customer_id}/accounts/{account_id}")
            response.raise_for_status()
            return AccountSummary.model_validate(response.json())
        finally:
            PROVIDER_LATENCY.labels(provider="core_bank", operation="get_account").observe(
                monotonic() - started
            )

    async def get_beneficiary(self, customer_id: str, beneficiary_id: str) -> Beneficiary:
        response = await self._client.get(
            f"/v1/customers/{customer_id}/beneficiaries/{beneficiary_id}"
        )
        response.raise_for_status()
        beneficiary = Beneficiary.model_validate(response.json())
        if not beneficiary.active:
            raise ValueError("beneficiary is inactive")
        return beneficiary

    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout)),
        wait=wait_exponential_jitter(initial=0.2, max=2),
        stop=stop_after_attempt(2),
        reraise=True,
    )
    async def execute_payment(
        self, customer_id: str, draft: PaymentDraft, *, idempotency_key: str
    ) -> PaymentExecution:
        started = monotonic()
        try:
            response = await self._client.post(
                f"/v1/customers/{customer_id}/payments",
                json=draft.model_dump(mode="json"),
                headers={"Idempotency-Key": idempotency_key},
            )
            response.raise_for_status()
            return PaymentExecution.model_validate(response.json())
        finally:
            PROVIDER_LATENCY.labels(provider="core_bank", operation="execute_payment").observe(
                monotonic() - started
            )

    async def close(self) -> None:
        await self._client.aclose()
