from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import EMBEDDING_DIMENSIONS, Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)

    credentials: Mapped[GoogleCredential | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    executions: Mapped[list[Execution]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    workspace_items: Mapped[list[WorkspaceItem]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    document_chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    sync_states: Mapped[list[SyncState]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    action_approvals: Mapped[list[ActionApproval]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="user")


class GoogleCredential(TimestampMixin, Base):
    __tablename__ = "google_credentials"
    __table_args__ = (UniqueConstraint("user_id", name="uq_google_credentials_user_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    granted_scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    token_expiry: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(back_populates="credentials")


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_created", "user_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )
    executions: Mapped[list[Execution]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Execution(TimestampMixin, Base):
    __tablename__ = "executions"
    __table_args__ = (
        Index("ix_executions_user_created", "user_id", "created_at"),
        Index("ix_executions_conversation", "conversation_id"),
        Index("ix_executions_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    intent: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    execution_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    user: Mapped[User] = relationship(back_populates="executions")
    conversation: Mapped[Conversation] = relationship(back_populates="executions")
    steps: Mapped[list[ExecutionStep]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", passive_deletes=True
    )
    approvals: Mapped[list[ActionApproval]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", passive_deletes=True
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="execution")


class ExecutionStep(TimestampMixin, Base):
    __tablename__ = "execution_steps"
    __table_args__ = (
        UniqueConstraint("execution_id", "step_id", name="uq_execution_steps_execution_step"),
        Index("ix_execution_steps_execution_status", "execution_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("executions.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[str] = mapped_column(String(128), nullable=False)
    service: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    execution: Mapped[Execution] = relationship(back_populates="steps")


class WorkspaceItem(TimestampMixin, Base):
    __tablename__ = "workspace_items"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "service",
            "external_resource_id",
            name="uq_workspace_items_user_service_resource",
        ),
        Index(
            "ix_workspace_items_user_service_source_updated",
            "user_id",
            "service",
            "source_updated_at",
        ),
        Index("ix_workspace_items_user_indexed", "user_id", "indexed_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    service: Mapped[str] = mapped_column(String(32), nullable=False)
    external_resource_id: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    searchable_text: Mapped[str] = mapped_column(Text, nullable=False)
    resource_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="workspace_items")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="workspace_item", cascade="all, delete-orphan", passive_deletes=True
    )


class DocumentChunk(TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "workspace_item_id", "chunk_index", name="uq_document_chunks_item_index"
        ),
        Index("ix_document_chunks_user_created", "user_id", "created_at"),
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspace_items.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)

    workspace_item: Mapped[WorkspaceItem] = relationship(back_populates="chunks")
    user: Mapped[User] = relationship(back_populates="document_chunks")


class SyncState(Base):
    __tablename__ = "sync_state"
    __table_args__ = (
        UniqueConstraint("user_id", "service", name="uq_sync_state_user_service"),
        Index("ix_sync_state_user_status", "user_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    service: Mapped[str] = mapped_column(String(32), nullable=False)
    sync_cursor: Mapped[str | None] = mapped_column(Text)
    last_successful_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempted_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    user: Mapped[User] = relationship(back_populates="sync_states")


class ActionApproval(TimestampMixin, Base):
    __tablename__ = "action_approvals"
    __table_args__ = (
        UniqueConstraint(
            "execution_id", "step_id", name="uq_action_approvals_execution_step"
        ),
        Index("ix_action_approvals_user_status", "user_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("executions.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    proposed_action: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    execution: Mapped[Execution] = relationship(back_populates="approvals")
    user: Mapped[User] = relationship(back_populates="action_approvals")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
        Index("ix_audit_logs_execution", "execution_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    execution_id: Mapped[UUID | None] = mapped_column(ForeignKey("executions.id"))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="audit_logs")
    execution: Mapped[Execution | None] = relationship(back_populates="audit_logs")
