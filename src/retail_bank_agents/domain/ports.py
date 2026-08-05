from typing import Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel

from retail_bank_agents.domain.models import (
    AccountSummary,
    Beneficiary,
    PaymentDraft,
    PaymentExecution,
    PaymentProposal,
    RetrievedDocument,
)

T = TypeVar("T", bound=BaseModel)


class LLMGateway(Protocol):
    async def parse(
        self,
        *,
        instructions: str,
        user_input: str,
        output_type: type[T],
        safety_identifier: str,
    ) -> T: ...

    async def generate(
        self,
        *,
        instructions: str,
        user_input: str,
        safety_identifier: str,
    ) -> str: ...


class KnowledgeRetriever(Protocol):
    async def search(
        self, query: str, *, customer_segment: str, top_k: int = 6
    ) -> list[RetrievedDocument]: ...


class BankGateway(Protocol):
    async def get_account(self, customer_id: str, account_id: str) -> AccountSummary: ...
    async def get_beneficiary(self, customer_id: str, beneficiary_id: str) -> Beneficiary: ...
    async def execute_payment(
        self, customer_id: str, draft: PaymentDraft, *, idempotency_key: str
    ) -> PaymentExecution: ...


class PaymentRepository(Protocol):
    async def create(self, proposal: PaymentProposal) -> PaymentProposal: ...
    async def get(self, payment_id: UUID) -> PaymentProposal | None: ...
    async def acquire_for_execution(
        self, payment_id: UUID, *, customer_id: str, approved_by: str
    ) -> PaymentProposal | None: ...
    async def save(self, proposal: PaymentProposal) -> PaymentProposal: ...


class AuditSink(Protocol):
    async def write(self, event_type: str, subject: str, payload: dict[str, object]) -> None: ...
