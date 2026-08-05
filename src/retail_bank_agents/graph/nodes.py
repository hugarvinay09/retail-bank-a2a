import json
from dataclasses import dataclass
from decimal import Decimal

import structlog
from pydantic import ValidationError

from retail_bank_agents.agents import prompts
from retail_bank_agents.config import Settings
from retail_bank_agents.domain.models import (
    AgentEnvelope,
    AgentName,
    ComplianceDecision,
    Intent,
    PaymentDraft,
    RiskAssessment,
    RouteDecision,
)
from retail_bank_agents.domain.ports import BankGateway, KnowledgeRetriever, LLMGateway
from retail_bank_agents.graph.state import AgentState
from retail_bank_agents.metrics import AGENT_CALLS, GUARDRAIL_BLOCKS
from retail_bank_agents.security import inspect_input

logger = structlog.get_logger(__name__)


def _envelope(
    state: AgentState,
    sender: AgentName,
    recipient: AgentName,
    message_type: str,
    payload: dict[str, object] | None = None,
) -> AgentEnvelope:
    return AgentEnvelope(
        sender=sender,
        recipient=recipient,
        message_type=message_type,
        correlation_id=state["correlation_id"],
        payload=payload or {},
    )


@dataclass(slots=True)
class AgentNodes:
    settings: Settings
    llm: LLMGateway
    retriever: KnowledgeRetriever
    bank: BankGateway

    async def guardrail(self, state: AgentState) -> dict[str, object]:
        sanitized, violations, blocked = inspect_input(
            state["user_input"], self.settings.max_input_chars
        )
        if blocked:
            for violation in violations:
                GUARDRAIL_BLOCKS.labels(reason=violation).inc()
        AGENT_CALLS.labels(agent="guardrail", status="blocked" if blocked else "ok").inc()
        return {
            "sanitized_input": sanitized,
            "blocked": blocked,
            "warnings": violations,
            "envelopes": [
                _envelope(
                    state,
                    AgentName.GUARDRAIL,
                    AgentName.ROUTER,
                    "input_assessment",
                    {"blocked": blocked, "violation_codes": violations},
                )
            ],
        }

    async def router(self, state: AgentState) -> dict[str, object]:
        if state.get("blocked", False):
            route = RouteDecision(
                intent=Intent.BLOCKED,
                confidence=1.0,
                rationale_code="unsafe_or_unsupported",
            )
        else:
            route = await self.llm.parse(
                instructions=prompts.ROUTER,
                user_input=state["sanitized_input"],
                output_type=RouteDecision,
                safety_identifier=state["safety_identifier"],
            )
            if route.confidence < 0.65:
                route = RouteDecision(
                    intent=Intent.SUPPORT,
                    confidence=route.confidence,
                    rationale_code="customer_support",
                )
        AGENT_CALLS.labels(agent="router", status="ok").inc()
        return {
            "route": route,
            "intent": route.intent,
            "envelopes": [
                _envelope(
                    state,
                    AgentName.ROUTER,
                    AgentName(route.intent.value)
                    if route.intent.value in AgentName._value2member_map_
                    else AgentName.SYNTHESIS,
                    "route_decision",
                    {"intent": route.intent.value, "confidence": route.confidence},
                )
            ],
        }

    async def knowledge(self, state: AgentState) -> dict[str, object]:
        if not self.settings.enable_knowledge:
            return {"documents": [], "warnings": ["knowledge_temporarily_disabled"]}
        documents = await self.retriever.search(
            state["sanitized_input"], customer_segment=state["customer_segment"], top_k=6
        )
        AGENT_CALLS.labels(agent="knowledge", status="ok" if documents else "empty").inc()
        return {
            "documents": documents,
            "warnings": [] if documents else ["no_approved_evidence"],
            "envelopes": [
                _envelope(
                    state,
                    AgentName.KNOWLEDGE,
                    AgentName.COMPLIANCE,
                    "retrieval_result",
                    {"document_ids": [doc.id for doc in documents]},
                )
            ],
        }

    async def accounts(self, state: AgentState) -> dict[str, object]:
        if not self.settings.enable_account_reads:
            return {"warnings": ["account_reads_temporarily_disabled"]}
        route = state["route"]
        account_id = route.required_account_id
        if not account_id and len(state["allowed_account_ids"]) == 1:
            account_id = next(iter(state["allowed_account_ids"]))
        if not account_id or account_id not in state["allowed_account_ids"]:
            AGENT_CALLS.labels(agent="accounts", status="denied").inc()
            return {"warnings": ["account_selection_required"]}
        account = await self.bank.get_account(state["customer_id"], account_id)
        AGENT_CALLS.labels(agent="accounts", status="ok").inc()
        return {
            "account": account,
            "envelopes": [
                _envelope(
                    state,
                    AgentName.ACCOUNTS,
                    AgentName.COMPLIANCE,
                    "account_result",
                    {"account_id": account.account_id},
                )
            ],
        }

    async def payment(self, state: AgentState) -> dict[str, object]:
        if not self.settings.enable_payment_proposals:
            return {"warnings": ["payment_proposals_temporarily_disabled"]}
        try:
            draft = await self.llm.parse(
                instructions=prompts.PAYMENT_EXTRACTOR,
                user_input=state["sanitized_input"],
                output_type=PaymentDraft,
                safety_identifier=state["safety_identifier"],
            )
        except ValidationError:
            AGENT_CALLS.labels(agent="payments", status="invalid").inc()
            return {"warnings": ["payment_details_missing_or_invalid"]}
        warnings: list[str] = []
        if draft.source_account_id not in state["allowed_account_ids"]:
            warnings.append("source_account_not_authorized")
        if draft.currency not in self.settings.allowed_currencies:
            warnings.append("currency_not_supported")
        if draft.amount > Decimal(str(self.settings.max_payment_amount)):
            warnings.append("amount_above_digital_limit")
        if warnings:
            AGENT_CALLS.labels(agent="payments", status="denied").inc()
            return {"warnings": warnings}
        await self.bank.get_beneficiary(state["customer_id"], draft.beneficiary_id)
        AGENT_CALLS.labels(agent="payments", status="proposed").inc()
        return {
            "payment_draft": draft,
            "envelopes": [
                _envelope(
                    state,
                    AgentName.PAYMENTS,
                    AgentName.FRAUD,
                    "payment_proposal",
                    {
                        "source_account_id": draft.source_account_id,
                        "beneficiary_id": draft.beneficiary_id,
                        "amount": str(draft.amount),
                        "currency": draft.currency,
                    },
                )
            ],
        }

    async def fraud(self, state: AgentState) -> dict[str, object]:
        draft = state.get("payment_draft")
        if not draft:
            return {"warnings": ["payment_risk_not_evaluated"]}
        # Replace with the bank's real-time fraud service.
        # This conservative adapter is deterministic.
        ratio = float(draft.amount / Decimal(str(self.settings.max_payment_amount)))
        score = min(100, int(15 + ratio * 70))
        decision = "deny" if score >= 85 else "review" if score >= 60 else "allow"
        reasons = ["high_value"] if score >= 60 else []
        risk = RiskAssessment(score=score, decision=decision, reason_codes=reasons)
        AGENT_CALLS.labels(agent="fraud", status=decision).inc()
        return {
            "risk": risk,
            "envelopes": [
                _envelope(
                    state,
                    AgentName.FRAUD,
                    AgentName.COMPLIANCE,
                    "risk_assessment",
                    {"decision": decision, "reason_codes": reasons},
                )
            ],
        }

    async def compliance(self, state: AgentState) -> dict[str, object]:
        decision = "allow"
        reasons: list[str] = []
        risk = state.get("risk")
        if state.get("intent") == Intent.PAYMENT:
            if not state.get("payment_draft") or not risk:
                decision, reasons = "deny", ["incomplete_payment_assessment"]
            elif risk.decision == "deny":
                decision, reasons = "deny", risk.reason_codes
            elif risk.decision == "review":
                decision, reasons = "review", risk.reason_codes
        compliance = ComplianceDecision(
            decision=decision,
            reason_codes=reasons,
            policy_version="retail-payments-2026-08",
        )
        AGENT_CALLS.labels(agent="compliance", status=decision).inc()
        return {
            "compliance": compliance,
            "envelopes": [
                _envelope(
                    state,
                    AgentName.COMPLIANCE,
                    AgentName.SYNTHESIS,
                    "compliance_decision",
                    {"decision": decision, "policy_version": compliance.policy_version},
                )
            ],
        }

    async def support(self, state: AgentState) -> dict[str, object]:
        text = await self.llm.generate(
            instructions=prompts.SUPPORT,
            user_input=state["sanitized_input"],
            safety_identifier=state["safety_identifier"],
        )
        AGENT_CALLS.labels(agent="support", status="ok").inc()
        return {"final_text": text}

    async def synthesize(self, state: AgentState) -> dict[str, object]:
        if state.get("blocked"):
            return {
                "final_text": (
                    "I can’t process that request because it contains unsafe instructions or "
                    "sensitive authentication data. Remove passwords, PINs, CVVs, and full card "
                    "numbers, then try again."
                )
            }
        if state.get("final_text"):
            return {}

        compliance = state.get("compliance")
        evidence: dict[str, object] = {
            "customer_request": state["sanitized_input"],
            "intent": state.get("intent", Intent.SUPPORT).value,
            "warnings": state.get("warnings", []),
            "compliance": compliance.model_dump(mode="json") if compliance else None,
        }
        if state.get("account"):
            evidence["account_result"] = state["account"].model_dump(mode="json")
        if state.get("payment_draft"):
            evidence["payment_proposal"] = state["payment_draft"].model_dump(mode="json")
            evidence["risk"] = state["risk"].model_dump(mode="json") if state.get("risk") else None
            evidence["mandatory_notice"] = "Approval is required; the payment has not executed."
        if state.get("documents"):
            evidence["approved_evidence"] = [
                {"citation": index, **doc.model_dump(mode="json")}
                for index, doc in enumerate(state["documents"], start=1)
            ]
        text = await self.llm.generate(
            instructions=prompts.SYNTHESIS,
            user_input=json.dumps(evidence, default=str),
            safety_identifier=state["safety_identifier"],
        )
        AGENT_CALLS.labels(agent="synthesis", status="ok").inc()
        return {"final_text": text}
