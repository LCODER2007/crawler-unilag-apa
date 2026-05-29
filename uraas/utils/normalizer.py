"""Title normalization utilities for gap analysis deduplication."""

import re


def normalize_title(title: str) -> str:
    """
    Lowercase, strip punctuation, collapse whitespace.
    Used so 'Climate Change In Lagos.' and 'climate change in lagos'
    score ≥95% similarity under Levenshtein distance.
    """
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"[^\w\s]", " ", t)  # strip punctuation
    t = re.sub(r"\s+", " ", t).strip()
    return t
