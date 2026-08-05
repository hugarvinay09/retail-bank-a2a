from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from retail_bank_agents.domain.models import PaymentProposal, PaymentStatus


class Base(DeclarativeBase):
    pass


class PaymentRow(Base):
    __tablename__ = "payment_proposals"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    idempotency_key: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(256))
    bank_reference: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class AuditRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True, nullable=False
    )
    integrity_version: Mapped[str] = mapped_column(String(16), default="v1", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1_800,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


class SQLPaymentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    def _to_row(proposal: PaymentProposal) -> PaymentRow:
        return PaymentRow(
            id=proposal.id,
            customer_id=proposal.customer_id,
            status=proposal.status.value,
            idempotency_key=proposal.idempotency_key,
            payload=proposal.model_dump(mode="json"),
            approved_by=proposal.approved_by,
            bank_reference=proposal.bank_reference,
            created_at=proposal.created_at,
            expires_at=proposal.expires_at,
        )

    @staticmethod
    def _to_domain(row: PaymentRow) -> PaymentProposal:
        payload = dict(row.payload)
        payload.update(
            {
                "status": row.status,
                "approved_by": row.approved_by,
                "bank_reference": row.bank_reference,
            }
        )
        return PaymentProposal.model_validate(payload)

    async def create(self, proposal: PaymentProposal) -> PaymentProposal:
        async with self._sessions.begin() as session:
            session.add(self._to_row(proposal))
        return proposal

    async def get(self, payment_id: UUID) -> PaymentProposal | None:
        async with self._sessions() as session:
            row = await session.get(PaymentRow, payment_id)
            return self._to_domain(row) if row else None

    async def acquire_for_execution(
        self, payment_id: UUID, *, customer_id: str, approved_by: str
    ) -> PaymentProposal | None:
        """Compare-and-set protects against duplicate approvals across replicas."""
        async with self._sessions.begin() as session:
            statement = (
                select(PaymentRow)
                .where(PaymentRow.id == payment_id, PaymentRow.customer_id == customer_id)
                .with_for_update()
            )
            row = (await session.execute(statement)).scalar_one_or_none()
            if row is None or row.status != PaymentStatus.PENDING_APPROVAL.value:
                return None
            if row.expires_at <= datetime.now(UTC):
                row.status = PaymentStatus.EXPIRED.value
                return None
            row.status = PaymentStatus.EXECUTING.value
            row.approved_by = approved_by
            await session.flush()
            return self._to_domain(row)

    async def save(self, proposal: PaymentProposal) -> PaymentProposal:
        async with self._sessions.begin() as session:
            row = await session.get(PaymentRow, proposal.id, with_for_update=True)
            if row is None:
                raise LookupError("payment proposal not found")
            row.status = proposal.status.value
            row.payload = proposal.model_dump(mode="json")
            row.approved_by = proposal.approved_by
            row.bank_reference = proposal.bank_reference
        return proposal


class SQLAuditSink:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def write(self, event_type: str, subject: str, payload: dict[str, object]) -> None:
        # In production, stream this append-only table to immutable S3 Object Lock/Audit Lake.
        async with self._sessions.begin() as session:
            session.add(AuditRow(event_type=event_type, subject=subject, payload=payload))
