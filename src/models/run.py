import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, JSON, ForeignKey, Enum as SAEnum, Integer
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    workflow_type: Mapped[str] = mapped_column(
        SAEnum("requirements", "planning", "codegen", name="workflow_type"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        SAEnum("pending", "running", "awaiting_human", "completed", "failed", "cancelled", name="run_status"),
        default="pending",
        nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    thread_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    current_node: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
