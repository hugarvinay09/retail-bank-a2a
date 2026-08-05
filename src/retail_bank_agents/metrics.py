from prometheus_client import Counter, Histogram

REQUESTS = Counter("bank_agent_requests_total", "Agent requests", ["route", "status"])
LATENCY = Histogram(
    "bank_agent_request_duration_seconds",
    "End-to-end request latency",
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30),
)
AGENT_CALLS = Counter("bank_agent_node_calls_total", "Calls by graph node", ["agent", "status"])
PAYMENTS = Counter("bank_agent_payments_total", "Payment lifecycle events", ["event", "status"])
GUARDRAIL_BLOCKS = Counter(
    "bank_agent_guardrail_blocks_total", "Requests blocked by guardrail", ["reason"]
)
PROVIDER_LATENCY = Histogram(
    "bank_agent_provider_duration_seconds", "Provider call latency", ["provider", "operation"]
)
