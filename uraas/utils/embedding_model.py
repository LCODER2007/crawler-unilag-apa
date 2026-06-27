"""
Lazy-loaded Model2Vec embedding singleton with graceful degradation.

Uses minishlab/potion-base-8M (~30MB static embeddings, numpy-only) so the
semantic half of alignment scoring runs comfortably inside the Flask process
on a small Render instance. If the model can't load (no network on first
boot, missing dependency), the alignment engine silently falls back to
keyword-only scoring — the dashboard never 500s.
"""

import logging
import os
import threading

# Windows lacks symlink privileges for the HF cache by default; harmless on Linux.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """Thread-safe lazy singleton around model2vec.StaticModel."""

    MODEL_NAME = os.getenv("URAAS_EMBED_MODEL", "minishlab/potion-base-8M")

    _model = None
    _failed = False
    _lock = threading.Lock()

    @classmethod
    def get(cls):
        """Return the StaticModel, or None if unavailable (keyword-only mode)."""
        if cls._model is not None or cls._failed:
            return cls._model
        with cls._lock:
            if cls._model is None and not cls._failed:
                try:
                    from model2vec import StaticModel

                    cls._model = StaticModel.from_pretrained(cls.MODEL_NAME)
                    logger.info("Embedding model loaded: %s", cls.MODEL_NAME)
                except Exception as e:
                    logger.warning(
                        "Embedding model unavailable -> keyword-only alignment: %s", e
                    )
                    cls._failed = True
        return cls._model

    @classmethod
    def encode(cls, texts):
        """Encode a list of strings -> np.ndarray, or None when unavailable."""
        model = cls.get()
        if model is None:
            return None
        try:
            return model.encode(texts)
        except Exception as e:
            logger.warning("Embedding encode failed: %s", e)
            return None

    @classmethod
    def is_available(cls) -> bool:
        return cls.get() is not None
