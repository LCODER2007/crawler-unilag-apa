"""
Centralized Special Collections seed keywords used by spiders + pipeline.

The exhaustive 133-term taxonomy lives in `uraas.utils.ai_classifier.SPECIAL_COLLECTIONS`
(that's the ground truth used for classification/scoring). The constants here are the
*crawler seed terms*: the short, high-signal phrases we inject into upstream search APIs
(OpenAlex / Crossref / arXiv) to oversample SC-relevant papers. Keeping them small keeps
URLs short and avoids hammering the APIs with 100+ OR clauses.
"""

from typing import List

from uraas.utils.ai_classifier import SPECIAL_COLLECTIONS

# Hand-picked seeds per category: the 2-3 most distinctive, low-ambiguity phrases.
# These get used directly in API search params, so they must be unambiguous enough
# that a vanilla full-text search returns relevant hits.
SC_SEED_KEYWORDS: List[str] = [
    # Indigenous Knowledge
    "indigenous knowledge",
    "traditional knowledge",
    "ethnobotany",
    "traditional ecological knowledge",
    # African Literature
    "postcolonial literature",
    "african literature",
    "oral literature",
    # Cultural Heritage
    "cultural heritage",
    "intangible heritage",
    "oral history",
    # Postcolonial Studies
    "postcolonialism",
    "decolonization",
    "decolonial",
    # Pan-African Studies
    "pan-africanism",
    "african renaissance",
    # African Philosophy
    "ubuntu philosophy",
    "african philosophy",
    # Ethnomusicology
    "ethnomusicology",
    "african music",
    "traditional music",
]

# OpenAlex concept search terms — these match against OpenAlex's concept taxonomy
# (broader than free-text). Used in concepts.display_name.search filter.
SC_OPENALEX_CONCEPTS: List[str] = [
    "indigenous",
    "postcolonial",
    "ethnography",
    "cultural heritage",
    "decolonization",
    "ubuntu",
    "ethnomusicology",
    "oral tradition",
]


def all_classifier_keywords() -> List[str]:
    """Full 133-term list used by the in-pipeline classifier for scoring."""
    out = []
    for kws in SPECIAL_COLLECTIONS.values():
        out.extend(kws)
    return out
