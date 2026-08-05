"""Local-only bank sandbox. Never deploy this module to a real bank environment."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException

from retail_bank_agents.domain.models import PaymentDraft

app = FastAPI(title="Local Bank Sandbox")
_idempotency: dict[str, dict[str, object]] = {}


@app.get("/v1/customers/{customer_id}/accounts/{account_id}")
async def account(customer_id: str, account_id: str) -> dict[str, object]:
    if customer_id != "cust-001" or account_id != "acct-001":
        raise HTTPException(status_code=404, detail="not_found")
    return {
        "account_id": account_id,
        "account_type": "checking",
        "masked_number": "•••• 0042",
        "currency": "INR",
        "available_balance": "125000.00",
        "ledger_balance": "127500.00",
        "as_of": datetime.now(UTC).isoformat(),
    }


@app.get("/v1/customers/{customer_id}/beneficiaries/{beneficiary_id}")
async def beneficiary(customer_id: str, beneficiary_id: str) -> dict[str, object]:
    if customer_id != "cust-001" or beneficiary_id != "ben-001":
        raise HTTPException(status_code=404, detail="not_found")
    return {
        "beneficiary_id": beneficiary_id,
        "display_name": "Demo Beneficiary",
        "bank_name": "Sandbox Bank",
        "masked_account": "•••• 7711",
        "active": True,
    }


@app.post("/v1/customers/{customer_id}/payments")
async def payment(
    customer_id: str,
    draft: PaymentDraft,
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict[str, object]:
    if customer_id != "cust-001":
        raise HTTPException(status_code=404, detail="not_found")
    if draft.amount > Decimal("100000"):
        raise HTTPException(status_code=422, detail="limit_exceeded")
    if idempotency_key in _idempotency:
        return _idempotency[idempotency_key]
    result = {
        "payment_id": str(UUID(idempotency_key)) if idempotency_key else str(uuid4()),
        "bank_reference": f"SBX-{uuid4().hex[:12].upper()}",
        "status": "accepted",
        "processed_at": datetime.now(UTC).isoformat(),
    }
    _idempotency[idempotency_key] = result
    return result
