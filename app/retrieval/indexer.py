import asyncio
from uuid import UUID

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentChunk, WorkspaceItem
from app.retrieval.chunking import chunk_text
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.normalization import NormalizedWorkspaceItem


class WorkspaceIndexer:
    def __init__(self, session: AsyncSession, embeddings: EmbeddingProvider) -> None:
        self._session = session
        self._embeddings = embeddings

    async def index_item(self, user_id: UUID, item: NormalizedWorkspaceItem) -> UUID:
        statement = (
            insert(WorkspaceItem)
            .values(
                user_id=user_id,
                service=item.service,
                external_resource_id=item.external_resource_id,
                title=item.title,
                searchable_text=item.searchable_text,
                resource_metadata=item.metadata,
                source_created_at=item.source_created_at,
                source_updated_at=item.source_updated_at,
                indexed_at=func.now(),
                deleted_at=None,
            )
            .on_conflict_do_update(
                constraint="uq_workspace_items_user_service_resource",
                set_={
                    "title": item.title,
                    "searchable_text": item.searchable_text,
                    WorkspaceItem.resource_metadata: item.metadata,
                    "source_created_at": item.source_created_at,
                    "source_updated_at": item.source_updated_at,
                    "indexed_at": func.now(),
                    "deleted_at": None,
                },
            )
            .returning(WorkspaceItem.id)
        )
        workspace_item_id = await self._session.scalar(statement)
        if workspace_item_id is None:
            raise RuntimeError("Workspace item upsert did not return an identifier")

        chunks = chunk_text(item.searchable_text)
        vectors = (
            await asyncio.to_thread(self._embeddings.embed_texts, chunks)
            if chunks
            else []
        )
        await self._session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.workspace_item_id == workspace_item_id,
                DocumentChunk.user_id == user_id,
            )
        )
        self._session.add_all(
            DocumentChunk(
                workspace_item_id=workspace_item_id,
                user_id=user_id,
                chunk_index=index,
                text=text,
                embedding=embedding,
            )
            for index, (text, embedding) in enumerate(zip(chunks, vectors, strict=True))
        )
        await self._session.flush()
        return workspace_item_id
