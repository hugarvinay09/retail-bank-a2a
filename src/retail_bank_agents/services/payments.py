from uuid import UUID

from retail_bank_agents.config import Settings
from retail_bank_agents.domain.errors import PaymentNotApprovable
from retail_bank_agents.domain.models import PaymentExecution, PaymentStatus
from retail_bank_agents.domain.ports import AuditSink, BankGateway, PaymentRepository
from retail_bank_agents.metrics import PAYMENTS
from retail_bank_agents.security import AuthContext


class PaymentApprovalService:
    def __init__(
        self,
        repository: PaymentRepository,
        bank: BankGateway,
        audit: AuditSink,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._bank = bank
        self._audit = audit
        self._settings = settings

    async def approve_and_execute(self, payment_id: UUID, auth: AuthContext) -> PaymentExecution:
        auth.require("payments:approve")
        if not self._settings.enable_payment_execution:
            raise PaymentNotApprovable("payment execution is temporarily disabled")
        if not auth.step_up_verified:
            raise PaymentNotApprovable("step-up authentication is required")
        proposal = await self._repository.acquire_for_execution(
            payment_id, customer_id=auth.customer_id, approved_by=auth.subject
        )
        if proposal is None:
            PAYMENTS.labels(event="approve", status="rejected").inc()
            raise PaymentNotApprovable("payment is missing, expired, or already processed")
        if proposal.draft.source_account_id not in auth.accounts:
            proposal.status = PaymentStatus.REJECTED
            await self._repository.save(proposal)
            raise PaymentNotApprovable("source account is no longer authorized")
        if proposal.risk.decision != "allow" or proposal.compliance.decision != "allow":
            proposal.status = PaymentStatus.REJECTED
            await self._repository.save(proposal)
            raise PaymentNotApprovable("payment requires bank operations review")

        await self._audit.write(
            "payment_execution_authorized",
            auth.subject,
            {
                "payment_id": str(payment_id),
                "customer_id": auth.customer_id,
                "policy_version": proposal.compliance.policy_version,
            },
        )
        try:
            execution = await self._bank.execute_payment(
                auth.customer_id,
                proposal.draft,
                idempotency_key=str(proposal.idempotency_key),
            )
            proposal.status = PaymentStatus.EXECUTED
            proposal.bank_reference = execution.bank_reference
            proposal.approved_by = auth.subject
            await self._repository.save(proposal)
            PAYMENTS.labels(event="execute", status="success").inc()
            await self._audit.write(
                "payment_executed",
                auth.subject,
                {
                    "payment_id": str(payment_id),
                    "bank_reference": execution.bank_reference,
                    "status": execution.status,
                },
            )
            return execution
        except Exception:
            proposal.status = PaymentStatus.FAILED
            await self._repository.save(proposal)
            PAYMENTS.labels(event="execute", status="failed").inc()
            await self._audit.write(
                "payment_execution_failed", auth.subject, {"payment_id": str(payment_id)}
            )
            raise
