from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Intent(StrEnum):
    KNOWLEDGE = "knowledge"
    ACCOUNTS = "accounts"
    PAYMENT = "payment"
    SUPPORT = "support"
    BLOCKED = "blocked"


class AgentName(StrEnum):
    GUARDRAIL = "guardrail"
    ROUTER = "router"
    KNOWLEDGE = "knowledge"
    ACCOUNTS = "accounts"
    PAYMENTS = "payments"
    FRAUD = "fraud"
    COMPLIANCE = "compliance"
    SYNTHESIS = "synthesis"


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    confidence: float = Field(ge=0, le=1)
    rationale_code: Literal[
        "policy_question",
        "account_information",
        "money_movement",
        "customer_support",
        "unsafe_or_unsupported",
    ]
    required_account_id: str | None = None


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str
    page: int | None = None
    section: str | None = None
    uri: str | None = None
    score: float = Field(ge=0, le=1)


class RetrievedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    title: str
    page: int | None = None
    section: str | None = None
    uri: str | None = None
    score: float = Field(ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AccountSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    account_type: str
    masked_number: str
    currency: str
    available_balance: Decimal
    ledger_balance: Decimal
    as_of: datetime


class Beneficiary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beneficiary_id: str
    display_name: str
    bank_name: str
    masked_account: str
    active: bool = True


class PaymentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_account_id: str
    beneficiary_id: str
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
    purpose: str = Field(min_length=3, max_length=140)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class RiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=100)
    decision: Literal["allow", "review", "deny"]
    reason_codes: list[str] = Field(default_factory=list)


class ComplianceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["allow", "review", "deny"]
    reason_codes: list[str] = Field(default_factory=list)
    policy_version: str


class PaymentStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    EXECUTED = "executed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


class PaymentProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    customer_id: str
    draft: PaymentDraft
    risk: RiskAssessment
    compliance: ComplianceDecision
    status: PaymentStatus = PaymentStatus.PENDING_APPROVAL
    idempotency_key: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    bank_reference: str | None = None
    approved_by: str | None = None


class PaymentExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_id: UUID
    bank_reference: str
    status: Literal["accepted", "completed", "failed"]
    processed_at: datetime


class AgentEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender: AgentName
    recipient: AgentName
    message_type: str
    correlation_id: UUID
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correlation_id: UUID
    answer: str
    intent: Intent
    citations: list[Citation] = Field(default_factory=list)
    payment_approval_id: UUID | None = None
    requires_human_approval: bool = False
    warnings: list[str] = Field(default_factory=list)
