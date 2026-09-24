from sqlalchemy import UniqueConstraint
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.db.base import EMBEDDING_DIMENSIONS, Base
from app.db.models import DocumentChunk

EXPECTED_TABLES = {
    "users",
    "google_credentials",
    "conversations",
    "messages",
    "executions",
    "execution_steps",
    "workspace_items",
    "document_chunks",
    "sync_state",
    "action_approvals",
    "audit_logs",
}


def unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def foreign_key_targets(table_name: str) -> set[str]:
    table = Base.metadata.tables[table_name]
    return {foreign_key.target_fullname for foreign_key in table.foreign_keys}


def test_required_tables_and_columns_are_registered() -> None:
    assert EXPECTED_TABLES == set(Base.metadata.tables)
    assert {
        "id",
        "user_id",
        "service",
        "external_resource_id",
        "title",
        "searchable_text",
        "metadata",
        "source_created_at",
        "source_updated_at",
        "indexed_at",
        "deleted_at",
        "created_at",
        "updated_at",
    } <= set(Base.metadata.tables["workspace_items"].columns.keys())
    assert {
        "id",
        "workspace_item_id",
        "user_id",
        "chunk_index",
        "text",
        "embedding",
        "created_at",
        "updated_at",
    } == set(Base.metadata.tables["document_chunks"].columns.keys())


def test_foreign_keys_preserve_user_scoping() -> None:
    assert foreign_key_targets("google_credentials") == {"users.id"}
    assert foreign_key_targets("messages") == {"conversations.id"}
    assert foreign_key_targets("execution_steps") == {"executions.id"}
    assert foreign_key_targets("document_chunks") == {
        "users.id",
        "workspace_items.id",
    }
    assert foreign_key_targets("action_approvals") == {
        "executions.id",
        "users.id",
    }


def test_required_uniqueness_constraints() -> None:
    assert ("email",) in unique_column_sets("users")
    assert ("user_id",) in unique_column_sets("google_credentials")
    assert ("execution_id", "step_id") in unique_column_sets("execution_steps")
    assert ("execution_id", "step_id") in unique_column_sets("action_approvals")
    assert ("user_id", "service", "external_resource_id") in unique_column_sets(
        "workspace_items"
    )
    assert ("workspace_item_id", "chunk_index") in unique_column_sets(
        "document_chunks"
    )
    assert ("user_id", "service") in unique_column_sets("sync_state")


def test_embedding_dimension_and_cosine_index() -> None:
    assert EMBEDDING_DIMENSIONS == 1536
    assert DocumentChunk.__table__.c.embedding.type.dim == EMBEDDING_DIMENSIONS

    embedding_index = next(
        index
        for index in DocumentChunk.__table__.indexes
        if index.name == "ix_document_chunks_embedding_hnsw"
    )
    assert embedding_index.dialect_options["postgresql"]["using"] == "hnsw"
    assert embedding_index.dialect_options["postgresql"]["ops"] == {
        "embedding": "vector_cosine_ops"
    }


def test_audit_log_foreign_keys_do_not_cascade() -> None:
    audit_logs = Base.metadata.tables["audit_logs"]
    assert all(foreign_key.ondelete is None for foreign_key in audit_logs.foreign_keys)


def test_database_configuration_uses_psycopg_three() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:password@localhost:5432/database",
    )

    assert make_url(settings.database_url).drivername == "postgresql+psycopg"
