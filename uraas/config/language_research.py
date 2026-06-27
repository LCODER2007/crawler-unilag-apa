"""
Language & Culture research detector — shared regex blueprints (Phase 7 cleanup).

Extracted from uraas/dashboard/app.py language_research() route to:
  1. Allow unit-testing the classifier in isolation.
  2. Eliminate the per-request re-compile of large regex patterns.
  3. Serve as the single source of truth for keyword lists.
"""
import re

# Tier-1: strong African-language / humanities signals (each match = 2 pts)
LANG_TIER1 = re.compile(
    r"\b(yoruba|igbo|hausa|pidgin|efik|tiv|fulani|ibibio|ijaw|kanuri"
    r"|sociolinguistics|lexicography|phonology|phonetics|morphosyntax"
    r"|oral tradition|oral literature|oral poetry|oral narrative|proverbs"
    r"|folklore|folktale|griot|african literature|nigerian literature"
    r"|postcolonial literature|literary criticism|literary theory|narratology"
    r"|language policy|multilingualism|bilingualism|code.switching"
    r"|indigenous language|vernacular|dialect continuum|pragmatics"
    r"|discourse analysis|stylistics|nollywood|yoruba drama|african theatre)\b",
    re.IGNORECASE,
)

# Tier-2: broad humanities signals (each match = 1 pt)
LANG_TIER2 = re.compile(
    r"\b(morphology|syntax|semantics|translation|literary|language|linguistic"
    r"|dialect|narrative|discourse|rhetoric|poetry|prose|fiction|novel|drama"
    r"|theatre|culture|cultural identity|cultural heritage|african studies|humanities)\b",
    re.IGNORECASE,
)

# Exclusion: STEM / clinical topics that accidentally hit tier-2 keywords
LANG_EXCLUDE = re.compile(
    r"\b(machine learning|deep learning|neural network|artificial intelligence"
    r"|clinical trial|randomized|patient|hospital|surgery|cancer|tumor"
    r"|cardiovascular|hypertension|diabetes|preeclampsia|concrete|cement"
    r"|compressive strength|tensile|alloy|composite|carbon emission"
    r"|ecological footprint|gdp|economic growth|galaxy|astrophysic|ionosphere"
    r"|plasma|quantum|semiconductor|mpox|covid|sars|influenza|malaria|hiv"
    r"|antibiotic|cybersecurity|blockchain|iot|cloud computing|petroleum"
    r"|crude oil|refinery|corrosion|mentoring|capacity building|faculty development)\b",
    re.IGNORECASE,
)

# Minimum relevance threshold: 2 combined tier-1/2 points, with ≥1 tier-1 hit
# or 3+ tier-2 hits.
LANG_MIN_SCORE = 2


def score_item(title: str, abstract: str) -> tuple[int, list[str]]:
    """Return (score, matched_terms) for a title+abstract pair.

    score == 0 means the item should be excluded.
    """
    text = (f"{title} {abstract}").lower()
    if LANG_EXCLUDE.search(text):
        return 0, []
    t1 = LANG_TIER1.findall(text)
    t2 = LANG_TIER2.findall(text)
    score = len(t1) * 2 + len(t2)
    if score < LANG_MIN_SCORE:
        return 0, []
    if not t1 and len(t2) < 3:
        return 0, []
    matched = list(dict.fromkeys(t1 + t2))  # deduplicate, preserve order
    return score, matched
