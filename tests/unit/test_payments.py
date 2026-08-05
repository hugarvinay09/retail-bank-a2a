from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from retail_bank_agents.domain.errors import PaymentNotApprovable
from retail_bank_agents.domain.models import (
    ComplianceDecision,
    PaymentDraft,
    PaymentProposal,
    PaymentStatus,
    RiskAssessment,
)
from retail_bank_agents.security import AuthContext
from retail_bank_agents.services.payments import PaymentApprovalService
from tests.conftest import FakeAudit, FakeBank, FakePayments


def proposal() -> PaymentProposal:
    return PaymentProposal(
        customer_id="cust-001",
        draft=PaymentDraft(
            source_account_id="acct-001",
            beneficiary_id="ben-001",
            amount=Decimal("1000"),
            currency="INR",
            purpose="monthly rent",
        ),
        risk=RiskAssessment(score=20, decision="allow"),
        compliance=ComplianceDecision(
            decision="allow", policy_version="policy-v1", reason_codes=[]
        ),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )


def auth(step_up: bool = True) -> AuthContext:
    return AuthContext(
        subject="user-1",
        customer_id="cust-001",
        scopes=frozenset({"payments:approve"}),
        accounts=frozenset({"acct-001"}),
        step_up_verified=step_up,
    )


@pytest.mark.asyncio
async def test_payment_executes_once_after_step_up(settings: object) -> None:
    repository, bank, audit = FakePayments(), FakeBank(), FakeAudit()
    item = proposal()
    await repository.create(item)
    service = PaymentApprovalService(repository, bank, audit, settings)
    result = await service.approve_and_execute(item.id, auth())
    assert result.bank_reference == "BANK-123"
    assert repository.items[item.id].status == PaymentStatus.EXECUTED
    with pytest.raises(PaymentNotApprovable):
        await service.approve_and_execute(item.id, auth())
    assert bank.executions == 1


@pytest.mark.asyncio
async def test_step_up_is_mandatory(settings: object) -> None:
    repository = FakePayments()
    item = proposal()
    await repository.create(item)
    service = PaymentApprovalService(repository, FakeBank(), FakeAudit(), settings)
    with pytest.raises(PaymentNotApprovable, match="step-up"):
        await service.approve_and_execute(item.id, auth(step_up=False))


@pytest.mark.asyncio
async def test_execution_kill_switch_fails_closed(settings: object) -> None:
    repository = FakePayments()
    item = proposal()
    await repository.create(item)
    disabled = settings.model_copy(update={"enable_payment_execution": False})
    service = PaymentApprovalService(repository, FakeBank(), FakeAudit(), disabled)
    with pytest.raises(PaymentNotApprovable, match="temporarily disabled"):
        await service.approve_and_execute(item.id, auth())
    assert item.status == PaymentStatus.PENDING_APPROVAL
