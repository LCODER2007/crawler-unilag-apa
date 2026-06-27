"""
Deterministic narrative templates — one human-readable insight sentence per
chart, generated server-side from the precomputed metrics and returned in the
API envelope's `narrative` field. No LLM dependency; failures return "" so a
narrative can never break an endpoint.
"""

import logging

logger = logging.getLogger(__name__)

NARRATIVE_TEMPLATES = {
    "alignment_profile": (
        "{institution} shows strongest alignment with “{top_pillar}” "
        "({top_score}/100 across {top_count} papers); {gap_count} of "
        "{pillar_count} pillars fall below the gap threshold of {threshold}."
    ),
    "alignment_gaps": (
        "{gap_count} research gaps identified across {framework_count} frameworks — "
        "the weakest area is “{worst_pillar}” ({worst_framework}) at {worst_score}/100."
    ),
    "intra_african": (
        "Intra-African collaboration is {pct}% — {ratio}× the continental "
        "average of {baseline}% (Research Policy, 2022). Top partner: {top_partner}."
    ),
    "intra_african_no_partner": (
        "Intra-African collaboration is {pct}% against a continental average "
        "of {baseline}% (Research Policy, 2022)."
    ),
    "country_pairs": (
        "{pair_count} active country pairs; the strongest link is "
        "{country_a}–{country_b} with {count} co-publications."
    ),
    "citation_velocity": (
        "Citations are accruing at {recent_rate} per year; on average papers "
        "gather {avg_first2y} citations in their first two years."
    ),
    "pan_african_share": (
        "{share}% of citations to this collection come from African "
        "institutions (computed for the {covered} most-cited works)."
    ),
}


def narrate(template_key: str, **values) -> str:
    """Render a narrative template; returns "" on any error."""
    template = NARRATIVE_TEMPLATES.get(template_key)
    if not template:
        return ""
    try:
        return template.format(**values)
    except Exception as e:
        logger.debug("narrate(%s) failed: %s", template_key, e)
        return ""
