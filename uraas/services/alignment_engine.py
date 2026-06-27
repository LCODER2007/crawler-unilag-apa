"""
Framework Alignment Engine — single source of truth for scoring papers
against AU charters, Agenda 2063 aspirations and regional-bloc themes.

Hybrid score per pillar (0-100):
    keyword  = min(1.0, matched_keyword_count / KEYWORD_SATURATION)
    semantic = max(0.0, cosine(embed(title+abstract), pillar_description_emb))
    hybrid   = 100 * (0.6 * semantic + 0.4 * keyword)     # embedding available
             = 100 * keyword                               # keyword-only fallback

Scores are computed ONCE at ingest (DatabaseStoragePipeline) or by
scripts/backfill_alignment.py and stored as JSON on items.alignment_scores.
Matched keywords are kept per pillar as auditable evidence (the credibility
layer surfaces them as chips, OSDG-style). Endpoints read precomputed
AlignmentAggregate rows — never score at request time.
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from uraas.config.alignment_frameworks import (
    ALIGNMENT_VERSION,
    FRAMEWORKS,
    GAP_THRESHOLD,
)
from uraas.utils.ai_classifier import _clean_text, _keyword_score
from uraas.utils.embedding_model import EmbeddingModel

logger = logging.getLogger(__name__)

# Keyword hits saturate the evidence score at this count.
KEYWORD_SATURATION = 4
# Pillars scoring below this are omitted from the stored JSON (keeps rows small).
MIN_RECORD = 5.0
# Evidence chips per pillar.
MAX_EVIDENCE_KEYWORDS = 6

SEMANTIC_WEIGHT = 0.6
KEYWORD_WEIGHT = 0.4
# Cosine similarity between unrelated academic texts and pillar anchors sits
# around 0.2-0.3 (embedding-space baseline). Rescale so that floor maps to 0,
# keeping topically aligned papers (>0.5 cosine) strongly separated.
SEMANTIC_FLOOR = 0.25

# ── Pillar embedding cache (per ALIGNMENT_VERSION, computed once) ────────────
_pillar_cache: Dict[int, Optional[dict]] = {}


def _pillar_embeddings() -> Optional[dict]:
    """{(framework_key, pillar_key): normalized vector} or None (no model)."""
    if ALIGNMENT_VERSION in _pillar_cache:
        return _pillar_cache[ALIGNMENT_VERSION]

    keys, texts = [], []
    for fkey, framework in FRAMEWORKS.items():
        for pkey, pillar in framework["pillars"].items():
            keys.append((fkey, pkey))
            # Embed name + description + keywords for a richer pillar anchor.
            texts.append(
                f"{pillar['name']}. {pillar['description']} "
                + ", ".join(pillar["keywords"])
            )

    vectors = EmbeddingModel.encode(texts)
    if vectors is None:
        _pillar_cache[ALIGNMENT_VERSION] = None
        return None

    import numpy as np

    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors = vectors / norms
    result = {k: vectors[i] for i, k in enumerate(keys)}
    _pillar_cache[ALIGNMENT_VERSION] = result
    return result


def scoring_mode() -> str:
    """'hybrid' when the embedding model is loaded, else 'keyword_only'."""
    return "hybrid" if EmbeddingModel.is_available() else "keyword_only"


def score_item_alignment(
    title: str, abstract: str, dc_subject: str = ""
) -> Tuple[Optional[str], int]:
    """Score one paper against every framework pillar.

    Returns (json_string_for_items.alignment_scores, ALIGNMENT_VERSION).
    The JSON omits pillars below MIN_RECORD; returns (None, version) when
    nothing aligns. Never raises — callers store the result at ingest."""
    try:
        text = _clean_text(f"{title or ''} {abstract or ''} {dc_subject or ''}")
        if not text.strip():
            return None, ALIGNMENT_VERSION

        pillar_embs = _pillar_embeddings()
        doc_vec = None
        if pillar_embs is not None:
            encoded = EmbeddingModel.encode([f"{title or ''}. {abstract or ''}"])
            if encoded is not None:
                import numpy as np

                doc_vec = encoded[0]
                norm = np.linalg.norm(doc_vec)
                doc_vec = doc_vec / norm if norm else None

        result = {}
        for fkey, framework in FRAMEWORKS.items():
            pillars_out = {}
            for pkey, pillar in framework["pillars"].items():
                hits, matched = _keyword_score(text, pillar["keywords"])
                keyword_score = min(1.0, hits / KEYWORD_SATURATION)

                semantic = 0.0
                if doc_vec is not None and pillar_embs is not None:
                    cosine = float(doc_vec @ pillar_embs[(fkey, pkey)])
                    # Rescale past the unrelated-text baseline so noise -> 0.
                    semantic = max(0.0, (cosine - SEMANTIC_FLOOR) / (1.0 - SEMANTIC_FLOOR))
                    hybrid = 100.0 * (
                        SEMANTIC_WEIGHT * semantic + KEYWORD_WEIGHT * keyword_score
                    )
                else:
                    hybrid = 100.0 * keyword_score

                if hybrid < MIN_RECORD:
                    continue
                pillars_out[pkey] = {
                    "score": round(hybrid, 1),
                    "semantic": round(semantic, 3),
                    "keyword": round(keyword_score, 3),
                    "matched_keywords": matched[:MAX_EVIDENCE_KEYWORDS],
                }
            if pillars_out:
                result[fkey] = {
                    "overall": round(
                        max(p["score"] for p in pillars_out.values()), 1
                    ),
                    "pillars": pillars_out,
                }

        return (json.dumps(result) if result else None), ALIGNMENT_VERSION
    except Exception as e:
        logger.error("score_item_alignment failed: %s", e)
        return None, ALIGNMENT_VERSION


def get_alignment(item) -> dict:
    """Parse an Item's stored alignment JSON ({} when absent/stale)."""
    if not getattr(item, "alignment_scores", None):
        return {}
    try:
        return json.loads(item.alignment_scores)
    except Exception:
        return {}


def recompute_aggregates(session, institution: Optional[str] = None) -> int:
    """Rebuild AlignmentAggregate rows for one institution (or "" = all).

    One row per (institution, framework, pillar): mean score over items where
    the pillar is present, count of items at/above GAP_THRESHOLD, and the
    top-5 item ids by score (evidence chips). Returns rows written."""
    from uraas.database import AlignmentAggregate, Item

    inst_key = institution or ""
    q = session.query(Item).filter(
        Item.special_collection_score > 0, Item.alignment_scores.isnot(None)
    )
    if institution:
        q = q.filter(Item.institution == institution)

    # (framework, pillar) -> list of (score, item_id)
    buckets: Dict[Tuple[str, str], List[Tuple[float, int]]] = {}
    for item in q.all():
        for fkey, fdata in get_alignment(item).items():
            for pkey, pdata in fdata.get("pillars", {}).items():
                buckets.setdefault((fkey, pkey), []).append(
                    (pdata.get("score", 0.0), item.id)
                )

    session.query(AlignmentAggregate).filter_by(institution=inst_key).delete()
    rows = 0
    for (fkey, pkey), entries in buckets.items():
        scores = [s for s, _ in entries]
        top = sorted(entries, reverse=True)[:5]
        session.add(
            AlignmentAggregate(
                institution=inst_key,
                framework=fkey,
                pillar=pkey,
                avg_score=round(sum(scores) / len(scores), 1),
                paper_count=sum(1 for s in scores if s >= GAP_THRESHOLD),
                top_item_ids=",".join(str(i) for _, i in top),
                computed_at=datetime.utcnow(),
            )
        )
        rows += 1
    session.commit()
    return rows
