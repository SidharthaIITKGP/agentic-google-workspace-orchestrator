"""Change document embeddings from 1536 to 384 dimensions.

Revision ID: 0002_embedding_dimension_384
Revises: 0001_initial_schema
"""

from collections.abc import Sequence

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa


revision: str = "0002_embedding_dimension_384"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing development embeddings cannot be converted meaningfully between
    # model dimensions. Chunks are reproducible; all other application data is retained.
    op.drop_index("ix_document_chunks_embedding_hnsw", table_name="document_chunks")
    op.execute("DELETE FROM document_chunks")
    op.drop_column("document_chunks", "embedding")
    op.add_column(
        "document_chunks", sa.Column("embedding", Vector(384), nullable=False)
    )
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_embedding_hnsw", table_name="document_chunks")
    op.execute("DELETE FROM document_chunks")
    op.drop_column("document_chunks", "embedding")
    op.add_column(
        "document_chunks", sa.Column("embedding", Vector(1536), nullable=False)
    )
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
