from functools import lru_cache
from threading import Lock
from typing import Protocol

from app.core.config import Settings


class EmbeddingProvider(Protocol):
    dimensions: int

    def embed_text(self, text: str) -> list[float]: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbeddingProvider:
    """Lazy, CPU-only normalized local embeddings."""

    def __init__(self, model_name: str, dimensions: int = 384) -> None:
        self.model_name = model_name
        self.dimensions = dimensions
        self._model = None
        self._load_lock = Lock()

    def embed_text(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("texts must contain non-empty strings")
        vectors = self._get_model().encode(
            texts,
            batch_size=min(32, len(texts)),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
            device="cpu",
        )
        result = [vector.astype(float).tolist() for vector in vectors]
        if any(len(vector) != self.dimensions for vector in result):
            raise RuntimeError("Embedding model dimension does not match configuration")
        return result

    def warmup(self) -> None:
        """Load the model once without generating or persisting an embedding."""
        self._get_model()

    def _get_model(self):
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self.model_name, device="cpu")
        return self._model


@lru_cache
def get_embedding_provider(
    model_name: str,
    dimensions: int,
) -> SentenceTransformerEmbeddingProvider:
    return SentenceTransformerEmbeddingProvider(model_name, dimensions)


def embedding_provider_from_settings(settings: Settings) -> SentenceTransformerEmbeddingProvider:
    return get_embedding_provider(settings.embedding_model, settings.embedding_dimensions)
