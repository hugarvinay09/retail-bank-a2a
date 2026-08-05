import pytest

from retail_bank_agents.graph.builder import build_graph
from retail_bank_agents.graph.nodes import AgentNodes
from retail_bank_agents.security import AuthContext
from retail_bank_agents.services.orchestrator import OrchestratorService
from tests.conftest import FakeAudit, FakeBank, FakeLLM, FakePayments, FakeRetriever


@pytest.mark.asyncio
async def test_orchestrator_persists_approved_payment_proposal(settings: object) -> None:
    payments, audit = FakePayments(), FakeAudit()
    graph = build_graph(
        AgentNodes(settings=settings, llm=FakeLLM(), retriever=FakeRetriever(), bank=FakeBank())
    )
    service = OrchestratorService(graph, payments, audit, settings)
    auth = AuthContext(
        subject="user-1",
        customer_id="cust-001",
        scopes=frozenset({"accounts:read", "payments:create"}),
        accounts=frozenset({"acct-001"}),
    )
    answer = await service.handle(
        "Transfer INR 1000 from acct-001 to ben-001 for monthly rent", auth
    )
    assert answer.requires_human_approval is True
    assert answer.payment_approval_id in payments.items
    assert audit.events[-1][0] == "agent_request_completed"
    assert "monthly rent" not in str(audit.events[-1])
