from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import respx

from retail_bank_agents.config import Settings
from retail_bank_agents.domain.models import PaymentDraft
from retail_bank_agents.providers.bank_api import BankAPI


@pytest.mark.asyncio
@respx.mock
async def test_bank_adapter_sends_idempotency_key_and_parses_types() -> None:
    settings = Settings(
        bank_api_base_url="https://bank.example",
        bank_api_token="opaque-service-token",
    )
    account_route = respx.get("https://bank.example/v1/customers/cust-001/accounts/acct-001").mock(
        return_value=httpx.Response(
            200,
            json={
                "account_id": "acct-001",
                "account_type": "checking",
                "masked_number": "•••• 0042",
                "currency": "INR",
                "available_balance": "125000.00",
                "ledger_balance": "127500.00",
                "as_of": datetime.now(UTC).isoformat(),
            },
        )
    )
    payment_route = respx.post("https://bank.example/v1/customers/cust-001/payments").mock(
        return_value=httpx.Response(
            200,
            json={
                "payment_id": str(uuid4()),
                "bank_reference": "BANK-123",
                "status": "accepted",
                "processed_at": datetime.now(UTC).isoformat(),
            },
        )
    )
    gateway = BankAPI(settings)
    try:
        account = await gateway.get_account("cust-001", "acct-001")
        execution = await gateway.execute_payment(
            "cust-001",
            PaymentDraft(
                source_account_id="acct-001",
                beneficiary_id="ben-001",
                amount=Decimal("1000"),
                currency="INR",
                purpose="monthly rent",
            ),
            idempotency_key="idempotency-123",
        )
    finally:
        await gateway.close()
    assert account.masked_number == "•••• 0042"
    assert execution.bank_reference == "BANK-123"
    assert account_route.called
    assert payment_route.calls.last.request.headers["Idempotency-Key"] == "idempotency-123"
