from datetime import UTC, datetime, timedelta
from uuid import uuid4

from langgraph.graph.state import CompiledStateGraph

from retail_bank_agents.config import Settings
from retail_bank_agents.domain.models import (
    AgentAnswer,
    Citation,
    Intent,
    PaymentProposal,
)
from retail_bank_agents.domain.ports import AuditSink, PaymentRepository
from retail_bank_agents.graph.state import AgentState
from retail_bank_agents.security import AuthContext, stable_safety_identifier


class OrchestratorService:
    def __init__(
        self,
        graph: CompiledStateGraph[AgentState, None, AgentState, AgentState],
        payments: PaymentRepository,
        audit: AuditSink,
        settings: Settings,
    ) -> None:
        self._graph = graph
        self._payments = payments
        self._audit = audit
        self._settings = settings

    async def handle(
        self, text: str, auth: AuthContext, *, customer_segment: str = "all"
    ) -> AgentAnswer:
        correlation_id = uuid4()
        initial: AgentState = {
            "correlation_id": correlation_id,
            "customer_id": auth.customer_id,
            "customer_segment": customer_segment,
            "allowed_account_ids": auth.accounts,
            "safety_identifier": stable_safety_identifier(
                auth.customer_id, self._settings.safety_hmac_key.get_secret_value()
            ),
            "user_input": text,
            "envelopes": [],
            "warnings": [],
        }
        state = await self._graph.ainvoke(initial)
        intent = state.get("intent", Intent.SUPPORT)
        if intent == Intent.ACCOUNTS:
            auth.require("accounts:read")
        payment_id = None
        requires_approval = False
        draft = state.get("payment_draft")
        risk = state.get("risk")
        compliance = state.get("compliance")
        if (
            intent == Intent.PAYMENT
            and draft
            and risk
            and compliance
            and risk.decision == "allow"
            and compliance.decision == "allow"
        ):
            auth.require("payments:create")
            proposal = PaymentProposal(
                customer_id=auth.customer_id,
                draft=draft,
                risk=risk,
                compliance=compliance,
                expires_at=datetime.now(UTC)
                + timedelta(seconds=self._settings.payment_approval_ttl_seconds),
            )
            await self._payments.create(proposal)
            payment_id = proposal.id
            requires_approval = True

        citations = [
            Citation(
                document_id=doc.id,
                title=doc.title,
                page=doc.page,
                section=doc.section,
                uri=doc.uri,
                score=doc.score,
            )
            for doc in state.get("documents", [])
        ]
        answer = AgentAnswer(
            correlation_id=correlation_id,
            answer=state.get("final_text", "Unable to complete the request safely."),
            intent=intent,
            citations=citations,
            payment_approval_id=payment_id,
            requires_human_approval=requires_approval,
            warnings=sorted(set(state.get("warnings", []))),
        )
        await self._audit.write(
            "agent_request_completed",
            auth.subject,
            {
                "correlation_id": str(correlation_id),
                "intent": intent.value,
                "payment_approval_id": str(payment_id) if payment_id else None,
                "warning_codes": answer.warnings,
                "agent_messages": [
                    {
                        "sender": envelope.sender.value,
                        "recipient": envelope.recipient.value,
                        "message_type": envelope.message_type,
                    }
                    for envelope in state.get("envelopes", [])
                ],
            },
        )
        return answer
