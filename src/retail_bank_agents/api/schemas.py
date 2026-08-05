from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from retail_bank_agents.domain.models import AgentAnswer, PaymentExecution


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=8_000)
    customer_segment: Literal["all", "mass", "affluent", "private"] = "all"


class ChatResponse(AgentAnswer):
    pass


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["APPROVE"]


class ApprovalResponse(PaymentExecution):
    pass


class PaymentStatusResponse(BaseModel):
    id: UUID
    status: str
    expires_at: str
    bank_reference: str | None = None
