from datetime import UTC, datetime
from decimal import Decimal
from typing import TypeVar
from uuid import UUID

import pytest
from pydantic import BaseModel

from retail_bank_agents.config import Settings
from retail_bank_agents.domain.models import (
    AccountSummary,
    Beneficiary,
    PaymentDraft,
    PaymentExecution,
    PaymentProposal,
    PaymentStatus,
    RetrievedDocument,
    RouteDecision,
)

T = TypeVar("T", bound=BaseModel)


class FakeLLM:
    async def parse(
        self,
        *,
        instructions: str,
        user_input: str,
        output_type: type[T],
        safety_identifier: str,
    ) -> T:
        del instructions, safety_identifier
        if output_type is RouteDecision:
            lower = user_input.lower()
            if "transfer" in lower:
                data = {
                    "intent": "payment",
                    "confidence": 0.98,
                    "rationale_code": "money_movement",
                }
            elif "balance" in lower:
                data = {
                    "intent": "accounts",
                    "confidence": 0.98,
                    "rationale_code": "account_information",
                    "required_account_id": "acct-001",
                }
            elif "fee" in lower:
                data = {
                    "intent": "knowledge",
                    "confidence": 0.95,
                    "rationale_code": "policy_question",
                }
            else:
                data = {
                    "intent": "support",
                    "confidence": 0.9,
                    "rationale_code": "customer_support",
                }
            return output_type.model_validate(data)
        if output_type is PaymentDraft:
            return output_type.model_validate(
                {
                    "source_account_id": "acct-001",
                    "beneficiary_id": "ben-001",
                    "amount": "1000.00",
                    "currency": "INR",
                    "purpose": "monthly rent",
                }
            )
        raise AssertionError(f"unexpected output type: {output_type}")

    async def generate(self, *, instructions: str, user_input: str, safety_identifier: str) -> str:
        del instructions, safety_identifier
        if "approved_evidence" in user_input:
            return "The fee is listed in the approved tariff [1]."
        if "payment_proposal" in user_input:
            return "The payment is proposed and has not executed. Approve it to continue."
        if "account_result" in user_input:
            return "Your available balance is INR 125,000.00."
        return "Please use the bank's official support channel."


class FakeRetriever:
    async def search(
        self, query: str, *, customer_segment: str, top_k: int = 6
    ) -> list[RetrievedDocument]:
        del query, customer_segment, top_k
        return [
            RetrievedDocument(
                id="policy-1",
                text="The approved service fee is INR 100.",
                title="Service Tariff",
                page=4,
                section="Fees",
                uri="s3://approved/service-tariff.pdf",
                score=0.93,
            )
        ]


class FakeBank:
    executions = 0

    async def get_account(self, customer_id: str, account_id: str) -> AccountSummary:
        assert customer_id == "cust-001"
        return AccountSummary(
            account_id=account_id,
            account_type="checking",
            masked_number="•••• 0042",
            currency="INR",
            available_balance=Decimal("125000"),
            ledger_balance=Decimal("127500"),
            as_of=datetime.now(UTC),
        )

    async def get_beneficiary(self, customer_id: str, beneficiary_id: str) -> Beneficiary:
        assert customer_id == "cust-001"
        return Beneficiary(
            beneficiary_id=beneficiary_id,
            display_name="Demo",
            bank_name="Sandbox",
            masked_account="•••• 7711",
        )

    async def execute_payment(
        self, customer_id: str, draft: PaymentDraft, *, idempotency_key: str
    ) -> PaymentExecution:
        del customer_id, draft, idempotency_key
        self.executions += 1
        return PaymentExecution(
            payment_id=UUID("00000000-0000-0000-0000-000000000001"),
            bank_reference="BANK-123",
            status="accepted",
            processed_at=datetime.now(UTC),
        )


class FakePayments:
    def __init__(self) -> None:
        self.items: dict[UUID, PaymentProposal] = {}

    async def create(self, proposal: PaymentProposal) -> PaymentProposal:
        self.items[proposal.id] = proposal
        return proposal

    async def get(self, payment_id: UUID) -> PaymentProposal | None:
        return self.items.get(payment_id)

    async def acquire_for_execution(
        self, payment_id: UUID, *, customer_id: str, approved_by: str
    ) -> PaymentProposal | None:
        proposal = self.items.get(payment_id)
        if (
            proposal is None
            or proposal.customer_id != customer_id
            or proposal.status != PaymentStatus.PENDING_APPROVAL
        ):
            return None
        proposal.status = PaymentStatus.EXECUTING
        proposal.approved_by = approved_by
        return proposal

    async def save(self, proposal: PaymentProposal) -> PaymentProposal:
        self.items[proposal.id] = proposal
        return proposal


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    async def write(self, event_type: str, subject: str, payload: dict[str, object]) -> None:
        self.events.append((event_type, subject, payload))


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="local",
        auth_disabled=True,
        safety_hmac_key="x" * 32,
        max_payment_amount=100_000,
        enable_payment_proposals=True,
        enable_payment_execution=True,
    )
