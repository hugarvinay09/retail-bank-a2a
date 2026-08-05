import operator
from typing import Annotated, NotRequired, TypedDict
from uuid import UUID

from retail_bank_agents.domain.models import (
    AccountSummary,
    AgentEnvelope,
    ComplianceDecision,
    Intent,
    PaymentDraft,
    RetrievedDocument,
    RiskAssessment,
    RouteDecision,
)


class AgentState(TypedDict):
    correlation_id: UUID
    customer_id: str
    customer_segment: str
    allowed_account_ids: frozenset[str]
    safety_identifier: str
    user_input: str
    sanitized_input: NotRequired[str]
    blocked: NotRequired[bool]
    route: NotRequired[RouteDecision]
    intent: NotRequired[Intent]
    documents: NotRequired[list[RetrievedDocument]]
    account: NotRequired[AccountSummary]
    payment_draft: NotRequired[PaymentDraft]
    risk: NotRequired[RiskAssessment]
    compliance: NotRequired[ComplianceDecision]
    final_text: NotRequired[str]
    envelopes: Annotated[list[AgentEnvelope], operator.add]
    warnings: Annotated[list[str], operator.add]
