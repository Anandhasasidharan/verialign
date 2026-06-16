from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Float,
    ForeignKey,
    Index,
    JSON,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Trace(Base):
    __tablename__ = "traces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    model = Column(String(255), nullable=False)
    request_json = Column(JSON, nullable=False)
    response_json = Column(JSON, nullable=False)
    verification_json = Column(JSON, nullable=False)

    claims = relationship("Claim", back_populates="trace", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_traces_created_at", "created_at"),
        Index("ix_traces_model", "model"),
    )


class Claim(Base):
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(
        Integer, ForeignKey("traces.id", ondelete="CASCADE"), nullable=False
    )
    claim_id = Column(String(100), nullable=False)
    text = Column(Text, nullable=False)
    status = Column(String(50), nullable=False)
    confidence = Column(Float, nullable=False)
    sentence_offset = Column(Integer, default=0)
    sources_json = Column(JSON, default=list)

    trace = relationship("Trace", back_populates="claims")

    __table_args__ = (
        Index("ix_claims_trace_id", "trace_id"),
        Index("ix_claims_status", "status"),
    )


class Contradiction(Base):
    __tablename__ = "contradictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(
        Integer, ForeignKey("traces.id", ondelete="CASCADE"), nullable=False
    )
    claim_a = Column(Text, nullable=False)
    claim_b = Column(Text, nullable=False)
    type = Column(String(50), nullable=False)
    confidence = Column(Float, nullable=False)

    __table_args__ = (Index("ix_contradictions_trace_id", "trace_id"),)


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(
        Integer, ForeignKey("traces.id", ondelete="CASCADE"), nullable=False
    )
    description = Column(Text, nullable=False)
    category = Column(String(100), nullable=False)
    priority = Column(String(20), nullable=False)
    related_claims_json = Column(JSON, default=list)

    __table_args__ = (Index("ix_checklist_trace_id", "trace_id"),)
