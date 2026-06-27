"""
Special Collections Decision Engine — the single source of truth for deciding
whether a paper belongs to URAAS's Special Collections (SC).

This is an in-process decision engine (no Elasticsearch/Celery): it layers
negative filters on top of the positive keyword taxonomy so that grey
literature, jargon, and STEM/medical noise are rejected, while genuine
indigenous-knowledge / African-literature / cultural-heritage work is kept.

It is consumed by:
  - the crawl pipeline (uraas/pipelines/database.py) at save time
  - the analytics SC gate (uraas/analytics/engine.py:_get_sc_item_ids)
  - the comparator (uraas/services/comparator_engine.py) via SC_FILTER
  - the re-classify/prune script (scripts/reclassify_and_prune_sc.py)

The keyword taxonomy itself lives in uraas.utils.ai_classifier.SPECIAL_COLLECTIONS
— we import it rather than redefine it.
"""

import re
from typing import List, Set, Tuple

from uraas.database import Item
from uraas.utils.ai_classifier import (
    SPECIAL_COLLECTIONS,
    _clean_text,
    _keyword_score,
)

# ── SQLAlchemy predicate: after re-scoring, score>0 ≡ Special Collection ──────
# Defined once here so every query (analytics, comparator) filters identically.
SC_FILTER = Item.special_collection_score > 0

# ── Category weighting ────────────────────────────────────────────────────────
# "Strong" categories can qualify a paper on their own. "Ethnic Languages &
# Groups" is support-only: it corroborates but cannot solely qualify a paper,
# because it contains bare ethnonym/language tokens that are false-positive
# magnets (e.g. "ss" → stainless steel, "ewe" → sheep).
STRONG_CATEGORIES: Set[str] = {
    "Indigenous Knowledge",
    "African Literature",
    "Cultural Heritage",
    "Postcolonial Studies",
    "Pan-African Studies",
    "African Philosophy",
    "Ethnomusicology",
}
SUPPORT_CATEGORIES: Set[str] = {"Ethnic Languages & Groups"}

# Bare tokens that must NOT qualify a paper unless they appear as a multi-word
# phrase or a second independent category also matches. These collide heavily
# with non-SC vocabulary.
AMBIGUOUS_TOKENS: Set[str] = {
    "ss",
    "ewe",
    "luo",
    "twi",
    "akan",
    "sotho",
    "venda",
    "oromo",
    "igbo",
    "hausa",
    "yoruba",
    "zulu",
    "xhosa",
    "shona",
    "somali",
    "wolof",
    "ganda",
    "fante",
    "chewa",
    "tsonga",
    "ndebele",
    "maasai",
    "fulani",
    "kikuyu",
    "swahili",
    "amharic",
    "tigrinya",
    "kinyarwanda",
    "lingala",
    "bambara",
    "setswana",
    "sesotho",
}

# Strong-category keywords that are themselves ambiguous: they appear as research
# *methods* or *regions* in otherwise non-SC papers (e.g. "ethnography" as a method,
# "ecowas"/"african union" as a study region, the homonym "african literature" =
# academic literature). A lone match from one of these needs SC context or a second
# corroborating category — same treatment as ambiguous ethnonyms.
AMBIGUOUS_STRONG: Set[str] = {
    "ethnography",
    "ecowas",
    "sadc",
    "african union",
    "african continental",
    "african development",
    "african literature",  # collides with "African [academic] literature review"
    "east african community",
}

# Cultural / linguistic context terms. When a bare ethnonym (AMBIGUOUS_TOKENS)
# co-occurs with one of these, the paper is genuinely about that people/language
# (e.g. "Personal name in Igbo Culture") rather than an incidental token collision
# (e.g. "Bacillus thuringiensis SS2"). Lets ethnonym-only papers qualify when the
# surrounding text confirms cultural/linguistic/historical intent.
SC_CONTEXT = re.compile(
    r"\b(culture|cultural|language|languages|linguistic|linguistics|"
    r"oral tradition|oral literature|folklore|folktale|folk tale|"
    r"traditional knowledge|indigenous knowledge|heritage|naming|"
    r"proverb|proverbs|ethnic group|ethnic groups|kingdom|"
    r"colonial rule|postcolonial|precolonial|indigenous|ancestral|"
    r"ritual|cosmology|worldview|mythology|customs|"
    r"griot|drumming|ethnomusicolog)\b",
    re.IGNORECASE,
)

# STEM / medical / engineering exclusion. Reused from the tiered logic that
# already exists in the dashboard's language endpoint (app.py). A paper that
# matches EXCLUDE is dropped unless it carries a *strong* SC signal.
EXCLUDE = re.compile(
    r"\b(machine learning|deep learning|neural network|artificial intelligence|"
    r"clinical trial|randomized|randomised|patient|hospital|surgery|cancer|tumor|tumour|"
    r"cardiovascular|hypertension|diabetes|preeclampsia|concrete|cement|"
    r"compressive strength|tensile|alloy|composite|carbon emission|"
    r"ecological footprint|gdp|economic growth|galaxy|astrophysic|ionosphere|"
    r"plasma|quantum|semiconductor|mpox|covid|sars|influenza|malaria|hiv|"
    r"antibiotic|cybersecurity|blockchain|iot|cloud computing|petroleum|"
    r"crude oil|refinery|corrosion|nanoparticle|photovoltaic|wastewater|"
    r"groundwater|finite element|stainless steel|catalyst|polymer)\b",
    re.IGNORECASE,
)


def _category_hits(text: str) -> List[Tuple[str, int, List[str]]]:
    """Return [(category, raw_match_count, matched_keywords)] for matched categories."""
    hits = []
    for category, keywords in SPECIAL_COLLECTIONS.items():
        count, matched = _keyword_score(text, keywords)
        if count >= 1:
            hits.append((category, count, matched))
    return hits


def _is_multiword(phrase: str) -> bool:
    return " " in phrase.strip()


def is_special_collection(
    title: str, abstract: str, dc_subject: str = ""
) -> Tuple[bool, float, List[str]]:
    """
    Decide whether a paper is a Special Collection.

    Returns (is_sc, score, categories).
      - score = sum(strong_matches * 3 + support_matches * 1); 0 when not SC.
      - categories = list of matched SC category names (only meaningful when is_sc).

    Decision gates (in order):
      1. Empty-text reject — require real title/abstract text.
      2. Ambiguous-token guard — bare ethnonym tokens only count via a multi-word
         phrase or a second independent category.
      3. STEM exclusion — EXCLUDE hit drops the paper unless a strong signal exists.
      4. Confidence — keep iff (>=1 strong category) OR (>=1 strong multi-word
         phrase and not excluded) OR (>=2 distinct categories).
    """
    # Gate 1: require title/abstract text (concept tags alone don't qualify).
    primary = _clean_text(f"{title or ''} {abstract or ''}").lower()
    if not primary.strip():
        return (False, 0.0, [])

    full = _clean_text(f"{title or ''} {abstract or ''} {dc_subject or ''}").lower()

    all_hits = _category_hits(full)
    if not all_hits:
        return (False, 0.0, [])

    has_context = bool(SC_CONTEXT.search(full))

    # A second-category corroboration check: count distinct categories with any
    # raw (pre-filter) hit, used to decide whether an ambiguous lone keyword counts.
    raw_categories = {h[0] for h in all_hits}
    has_second_category = len(raw_categories) >= 2

    def _filter_ambiguous(matched, ambiguous_set):
        """Keep keywords that aren't ambiguous, or that are corroborated by SC
        context / a second category. An ambiguous keyword (whether single- or
        multi-word, e.g. bare "igbo" or the homonym phrase "african literature")
        only counts when context or a second category corroborates it. A
        non-ambiguous multi-word phrase always counts."""
        kept = []
        for kw in matched:
            if kw.lower() in ambiguous_set:
                if has_context or has_second_category:
                    kept.append(kw)
            else:
                kept.append(kw)
        return kept

    # Gate 2: filter ambiguous matches in BOTH strong and support categories.
    # Bare ethnonyms ("igbo") and homonym method/region terms ("ethnography",
    # "ecowas", "african literature") only count alone when context corroborates —
    # this separates real ethnic/cultural studies from incidental token collisions.
    strong_hits = []
    for cat, count, matched in all_hits:
        if cat not in STRONG_CATEGORIES:
            continue
        kept = _filter_ambiguous(matched, AMBIGUOUS_STRONG)
        if kept:
            strong_hits.append((cat, len(kept), kept))

    support_hits = []
    for cat, count, matched in all_hits:
        if cat not in SUPPORT_CATEGORIES:
            continue
        kept = _filter_ambiguous(matched, AMBIGUOUS_TOKENS)
        if kept:
            support_hits.append((cat, len(kept), kept))

    qualifying = strong_hits + support_hits
    if not qualifying:
        return (False, 0.0, [])

    categories = [c for c, _, _ in qualifying]
    # A "qualifying phrase" is any multi-word matched keyword from a strong OR a
    # support category — multi-word ethnonym phrases (e.g. "yoruba cosmology",
    # "swahili coast") are specific enough to stand on their own.
    has_qualifying_phrase = any(
        _is_multiword(kw) for _, _, matched in qualifying for kw in matched
    )
    # A bare ethnonym that survived Gate 2 (i.e. context present) qualifies the
    # paper on its own — distinguishes "Igbo Culture" from "SS2".
    has_context_support = bool(support_hits) and has_context

    # Gate 3: STEM exclusion — needs a strong signal to survive.
    excluded = bool(EXCLUDE.search(full))
    if excluded and not strong_hits:
        return (False, 0.0, [])

    # Gate 4: confidence.
    keep = (
        bool(strong_hits)
        or (has_qualifying_phrase and not excluded)
        or (len(set(categories)) >= 2)
        or (has_context_support and not excluded)
    )
    if not keep:
        return (False, 0.0, [])

    score = float(sum(c * 3 for _, c, _ in strong_hits) + sum(c for _, c, _ in support_hits))
    if score <= 0:
        return (False, 0.0, [])

    return (True, score, categories)


def category_breakdown(title: str, abstract: str, dc_subject: str = "") -> List[dict]:
    """
    For a paper already known to be SC, return per-category detail for display:
    [{category, score, matched_keywords}]. Only the categories that actually
    qualified the paper (after the ambiguity/context gates) are returned, so the
    analytics breakdown matches the keep/drop decision exactly.
    """
    is_sc, _, categories = is_special_collection(title, abstract, dc_subject)
    if not is_sc:
        return []
    full = _clean_text(f"{title or ''} {abstract or ''} {dc_subject or ''}").lower()
    out = []
    for category in categories:
        count, matched = _keyword_score(full, SPECIAL_COLLECTIONS.get(category, []))
        weight = 3 if category in STRONG_CATEGORIES else 1
        out.append(
            {
                "category": category,
                "score": count * weight,
                "matched_keywords": matched[:6],
            }
        )
    out.sort(key=lambda x: -x["score"])
    return out


def score_text(title: str, abstract: str, dc_subject: str = "") -> Tuple[float, str]:
    """Convenience wrapper returning (score, comma-joined categories) for storage."""
    is_sc, score, categories = is_special_collection(title, abstract, dc_subject)
    return (score, ",".join(categories) if is_sc else "")


if __name__ == "__main__":
    # Tiny smoke check
    samples = [
        ("Yoruba cosmology and oral tradition in Ifa divination", ""),
        ("Compressive strength of recycled concrete aggregate", ""),
        ("Indigenous medicine for malaria among the Igbo", "ethnobotany traditional healing"),
        ("Deep learning for tumour segmentation", ""),
        ("A study of SS 304 stainless steel corrosion", ""),
        ("Ubuntu philosophy and African communalism", ""),
    ]
    for t, a in samples:
        print(is_special_collection(t, a), "::", t)
