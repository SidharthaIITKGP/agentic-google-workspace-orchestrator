"""Create the initial application schema.

Revision ID: 0001_initial_schema
Revises: None
"""

from collections.abc import Sequence

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
TIMESTAMP = sa.DateTime(timezone=True)
NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", UUID, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.Column("updated_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "google_credentials",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=False),
        sa.Column("granted_scopes", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("token_expiry", TIMESTAMP, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.Column("updated_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_google_credentials_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_google_credentials"),
        sa.UniqueConstraint("user_id", name="uq_google_credentials_user_id"),
    )

    op.create_table(
        "conversations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.Column("updated_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_conversations_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_user_created", "conversations", ["user_id", "created_at"])

    op.create_table(
        "messages",
        sa.Column("id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"]
    )

    op.create_table(
        "executions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("conversation_id", UUID, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("intent", JSONB, nullable=False),
        sa.Column("execution_plan", JSONB, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.Column("updated_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_executions_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_executions_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_executions"),
    )
    op.create_index("ix_executions_user_created", "executions", ["user_id", "created_at"])
    op.create_index("ix_executions_conversation", "executions", ["conversation_id"])
    op.create_index("ix_executions_status", "executions", ["status"])

    op.create_table(
        "execution_steps",
        sa.Column("id", UUID, nullable=False),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("step_id", sa.String(length=128), nullable=False),
        sa.Column("service", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("arguments", JSONB, nullable=False),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("error_details", JSONB, nullable=True),
        sa.Column("created_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.Column("updated_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["executions.id"],
            name="fk_execution_steps_execution_id_executions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_steps"),
        sa.UniqueConstraint(
            "execution_id", "step_id", name="uq_execution_steps_execution_step"
        ),
    )
    op.create_index(
        "ix_execution_steps_execution_status", "execution_steps", ["execution_id", "status"]
    )

    op.create_table(
        "workspace_items",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("service", sa.String(length=32), nullable=False),
        sa.Column("external_resource_id", sa.String(length=512), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("searchable_text", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("source_created_at", TIMESTAMP, nullable=True),
        sa.Column("source_updated_at", TIMESTAMP, nullable=True),
        sa.Column("indexed_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.Column("deleted_at", TIMESTAMP, nullable=True),
        sa.Column("created_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.Column("updated_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_workspace_items_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workspace_items"),
        sa.UniqueConstraint(
            "user_id",
            "service",
            "external_resource_id",
            name="uq_workspace_items_user_service_resource",
        ),
    )
    op.create_index(
        "ix_workspace_items_user_service_source_updated",
        "workspace_items",
        ["user_id", "service", "source_updated_at"],
    )
    op.create_index(
        "ix_workspace_items_user_indexed", "workspace_items", ["user_id", "indexed_at"]
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", UUID, nullable=False),
        sa.Column("workspace_item_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.Column("updated_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_item_id"],
            ["workspace_items.id"],
            name="fk_document_chunks_workspace_item_id_workspace_items",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_document_chunks_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.UniqueConstraint(
            "workspace_item_id", "chunk_index", name="uq_document_chunks_item_index"
        ),
    )
    op.create_index(
        "ix_document_chunks_user_created", "document_chunks", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "sync_state",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("service", sa.String(length=32), nullable=False),
        sa.Column("sync_cursor", sa.Text(), nullable=True),
        sa.Column("last_successful_sync", TIMESTAMP, nullable=True),
        sa.Column("last_attempted_sync", TIMESTAMP, nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_details", JSONB, nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_sync_state_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sync_state"),
        sa.UniqueConstraint("user_id", "service", name="uq_sync_state_user_service"),
    )
    op.create_index("ix_sync_state_user_status", "sync_state", ["user_id", "status"])

    op.create_table(
        "action_approvals",
        sa.Column("id", UUID, nullable=False),
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("step_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("proposed_action", JSONB, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.Column("updated_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["executions.id"],
            name="fk_action_approvals_execution_id_executions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_action_approvals_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_action_approvals"),
        sa.UniqueConstraint(
            "execution_id", "step_id", name="uq_action_approvals_execution_step"
        ),
    )
    op.create_index(
        "ix_action_approvals_user_status", "action_approvals", ["user_id", "status"]
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("execution_id", UUID, nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("details", JSONB, nullable=False),
        sa.Column("created_at", TIMESTAMP, server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_audit_logs_user_id_users"),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["executions.id"], name="fk_audit_logs_execution_id_executions"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index("ix_audit_logs_user_created", "audit_logs", ["user_id", "created_at"])
    op.create_index("ix_audit_logs_execution", "audit_logs", ["execution_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("action_approvals")
    op.drop_table("sync_state")
    op.drop_table("document_chunks")
    op.drop_table("workspace_items")
    op.drop_table("execution_steps")
    op.drop_table("executions")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("google_credentials")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector")
