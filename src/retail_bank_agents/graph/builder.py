from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from retail_bank_agents.domain.models import Intent
from retail_bank_agents.graph.nodes import AgentNodes
from retail_bank_agents.graph.state import AgentState


def _route_after_router(state: AgentState) -> str:
    return state.get("intent", Intent.SUPPORT).value


def _after_payment(state: AgentState) -> str:
    return "fraud" if state.get("payment_draft") else "compliance"


def build_graph(
    nodes: AgentNodes,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """A fixed graph keeps banking side effects inspectable and testable."""
    graph = StateGraph(AgentState)
    graph.add_node("guardrail", nodes.guardrail)
    graph.add_node("router", nodes.router)
    graph.add_node("knowledge", nodes.knowledge)
    graph.add_node("accounts", nodes.accounts)
    graph.add_node("payment", nodes.payment)
    graph.add_node("fraud", nodes.fraud)
    graph.add_node("compliance", nodes.compliance)
    graph.add_node("support", nodes.support)
    graph.add_node("synthesize", nodes.synthesize)

    graph.add_edge(START, "guardrail")
    graph.add_edge("guardrail", "router")
    graph.add_conditional_edges(
        "router",
        _route_after_router,
        {
            Intent.KNOWLEDGE.value: "knowledge",
            Intent.ACCOUNTS.value: "accounts",
            Intent.PAYMENT.value: "payment",
            Intent.SUPPORT.value: "support",
            Intent.BLOCKED.value: "synthesize",
        },
    )
    graph.add_edge("knowledge", "compliance")
    graph.add_edge("accounts", "compliance")
    graph.add_conditional_edges(
        "payment", _after_payment, {"fraud": "fraud", "compliance": "compliance"}
    )
    graph.add_edge("fraud", "compliance")
    graph.add_edge("compliance", "synthesize")
    graph.add_edge("support", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()
