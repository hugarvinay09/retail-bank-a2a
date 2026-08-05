from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.exceptions import RedisError
from sqlalchemy import text
from starlette.responses import Response

from retail_bank_agents.api.schemas import (
    ApprovalRequest,
    ApprovalResponse,
    ChatRequest,
    ChatResponse,
    PaymentStatusResponse,
)
from retail_bank_agents.domain.errors import PaymentNotApprovable
from retail_bank_agents.metrics import LATENCY, REQUESTS
from retail_bank_agents.security import AuthContext, get_auth_context

router = APIRouter()
Auth = Annotated[AuthContext, Depends(get_auth_context)]


def _container(request: Request) -> Any:
    return request.app.state.container


@router.get("/health/live", include_in_schema=False)
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", include_in_schema=False)
async def readiness(request: Request) -> dict[str, str]:
    container = _container(request)
    try:
        async with container.sessions() as session:
            await session.execute(text("SELECT 1"))
        await container.redis.ping()
        return {"status": "ready"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="dependencies_not_ready") from exc


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.post("/v1/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request, auth: Auth) -> ChatResponse:
    auth.require("assistant:use")
    container = _container(request)
    try:
        if not await container.rate_limiter.allow(auth.customer_id):
            raise HTTPException(status_code=429, detail="rate_limit_exceeded")
    except RedisError as exc:
        # Fail closed for a customer-facing banking endpoint.
        raise HTTPException(status_code=503, detail="rate_limiter_unavailable") from exc

    with LATENCY.time():
        try:
            answer = await container.orchestrator.handle(
                payload.message, auth, customer_segment=payload.customer_segment
            )
            REQUESTS.labels(route=answer.intent.value, status="ok").inc()
            return ChatResponse.model_validate(answer.model_dump())
        except HTTPException:
            raise
        except Exception as exc:
            REQUESTS.labels(route="unknown", status="error").inc()
            raise HTTPException(status_code=503, detail="agent_temporarily_unavailable") from exc


@router.get("/v1/payments/{payment_id}", response_model=PaymentStatusResponse)
async def payment_status(payment_id: UUID, request: Request, auth: Auth) -> PaymentStatusResponse:
    proposal = await _container(request).payment_repository.get(payment_id)
    if proposal is None or proposal.customer_id != auth.customer_id:
        raise HTTPException(status_code=404, detail="payment_not_found")
    return PaymentStatusResponse(
        id=proposal.id,
        status=proposal.status.value,
        expires_at=proposal.expires_at.isoformat(),
        bank_reference=proposal.bank_reference,
    )


@router.post(
    "/v1/payments/{payment_id}/approve",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
)
async def approve_payment(
    payment_id: UUID, payload: ApprovalRequest, request: Request, auth: Auth
) -> ApprovalResponse:
    del payload
    try:
        result = await _container(request).payment_service.approve_and_execute(payment_id, auth)
        return ApprovalResponse.model_validate(result.model_dump())
    except PaymentNotApprovable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
