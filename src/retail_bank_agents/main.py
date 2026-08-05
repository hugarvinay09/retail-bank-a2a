from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import structlog
import uvicorn
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from retail_bank_agents import __version__
from retail_bank_agents.api.routes import router
from retail_bank_agents.config import Settings, get_settings
from retail_bank_agents.graph.builder import build_graph
from retail_bank_agents.graph.nodes import AgentNodes
from retail_bank_agents.logging import configure_logging
from retail_bank_agents.providers.bank_api import BankAPI
from retail_bank_agents.providers.knowledge import PineconeCohereRetriever
from retail_bank_agents.providers.openai_gateway import OpenAIResponsesGateway
from retail_bank_agents.providers.rate_limit import RedisRateLimiter
from retail_bank_agents.repositories.database import (
    SQLAuditSink,
    SQLPaymentRepository,
    make_engine,
    make_session_factory,
)
from retail_bank_agents.services.orchestrator import OrchestratorService
from retail_bank_agents.services.payments import PaymentApprovalService
from retail_bank_agents.telemetry import configure_telemetry

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class Container:
    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    redis: Redis
    bank: BankAPI
    rate_limiter: RedisRateLimiter
    payment_repository: SQLPaymentRepository
    orchestrator: OrchestratorService
    payment_service: PaymentApprovalService


def build_container(settings: Settings) -> Container:
    engine = make_engine(settings.database_url)
    sessions = make_session_factory(engine)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    openai = OpenAIResponsesGateway(settings)
    bank = BankAPI(settings)
    retriever = PineconeCohereRetriever(settings, openai)
    payments = SQLPaymentRepository(sessions)
    audit = SQLAuditSink(sessions)
    graph = build_graph(AgentNodes(settings=settings, llm=openai, retriever=retriever, bank=bank))
    return Container(
        settings=settings,
        engine=engine,
        sessions=sessions,
        redis=redis,
        bank=bank,
        rate_limiter=RedisRateLimiter(redis),
        payment_repository=payments,
        orchestrator=OrchestratorService(graph, payments, audit, settings),
        payment_service=PaymentApprovalService(payments, bank, audit, settings),
    )


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    container = build_container(settings)
    application.state.container = container
    logger.info("application_started", version=__version__, environment=settings.environment)
    try:
        yield
    finally:
        await container.bank.close()
        await container.redis.aclose()
        await container.engine.dispose()
        logger.info("application_stopped")


_settings = get_settings()
configure_telemetry(_settings)
app = FastAPI(
    title="Retail Bank Agent-to-Agent API",
    version=__version__,
    docs_url="/docs" if _settings.environment != "prod" else None,
    redoc_url=None,
    lifespan=lifespan,
)
app.include_router(router)
FastAPIInstrumentor.instrument_app(app)


def run() -> None:
    uvicorn.run("retail_bank_agents.main:app", host="0.0.0.0", port=8080)  # noqa: S104


if __name__ == "__main__":
    run()
