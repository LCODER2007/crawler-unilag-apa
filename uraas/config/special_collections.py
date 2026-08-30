"""
Centralized Special Collections seed keywords used by spiders + pipeline.

The exhaustive 340+-term taxonomy lives in `uraas.utils.ai_classifier.SPECIAL_COLLECTIONS`
(that's the ground truth used for classification/scoring, across 8 categories). The
constants here are the *crawler seed terms*: the phrases we inject into upstream search
APIs (OpenAlex / Crossref / arXiv / ...) to oversample SC-relevant papers via fan-out
"seed:<term> AND institution" queries — one extra request per seed, so more seeds directly
means more distinct candidate papers surfaced (a term that never gets searched for can
never be found this way, no matter how well the classifier would score it once seen).

This used to be a hand-picked ~20-term subset ("keep URLs short, avoid hammering the
APIs"), which left ~320 taxonomy terms completely unused for discovery — live-tested
against the OpenAlex API (2026-07), every individual seed query here returns well under
the per-page result cap (single page, no deep pagination triggered), so the request-count
cost of using the full taxonomy is linear and modest (~1 request per seed per wave), not
exponential. We still exclude the taxonomy's own known-ambiguous bare tokens/phrases
(uraas.services.sc_engine.AMBIGUOUS_TOKENS / AMBIGUOUS_STRONG — bare ethnonyms like "ss"/
"ewe"/"igbo" and homonym terms like "ethnography"/"ecowas" that collide heavily with
unrelated vocabulary) since as *search* seeds (not post-hoc classifier signals) they'd
mostly return irrelevant noise that the sc_score_of() gate then has to reject one-by-one —
correct, but a waste of request budget compared to a same-or-better yield from the
unambiguous 300+ terms that remain.
"""

from typing import List

from uraas.services.sc_engine import AMBIGUOUS_STRONG, AMBIGUOUS_TOKENS
from uraas.utils.ai_classifier import SPECIAL_COLLECTIONS

_ambiguous = {t.lower() for t in AMBIGUOUS_TOKENS} | {
    t.lower() for t in AMBIGUOUS_STRONG
}

_all_taxonomy_terms = {kw.lower() for kws in SPECIAL_COLLECTIONS.values() for kw in kws}

# Every taxonomy term except the ones sc_engine itself flags as too ambiguous to
# stand alone. Sorted for a stable, diffable seed order across runs.
SC_SEED_KEYWORDS: List[str] = sorted(_all_taxonomy_terms - _ambiguous)


def all_classifier_keywords() -> List[str]:
    """Full taxonomy keyword list used by the in-pipeline classifier for scoring."""
    out = []
    for kws in SPECIAL_COLLECTIONS.values():
        out.extend(kws)
    return out
