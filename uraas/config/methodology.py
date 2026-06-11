"""
Per-metric methodology definitions — the "how is this computed" layer.

Served whole via GET /api/methodology (frontend caches it for the ⓘ tooltips)
and attached per-endpoint through responses.api_ok(methodology_key=...).

Every number on the dashboard must be auditable: formula, data source,
counting method, known limitations. This is the product's differentiator
versus closed bibliometric platforms (Barcelona Declaration on Open Research
Information, 2024; Leiden Ranking Open Edition).
"""

METHODOLOGY = {
    "alignment_score": {
        "title": "Framework Alignment Score",
        "formula": (
            "0.6 × semantic similarity (Model2Vec potion-base-8M cosine between the "
            "paper's title+abstract and the pillar description) + 0.4 × keyword "
            "evidence (matched pillar keywords, saturating at 4 hits). Scaled 0–100."
        ),
        "scale": "0–100 per pillar; institutional profile = mean over papers scoring ≥5.",
        "source": "Open metadata (OpenAlex, CC0); URAAS alignment engine v1.",
        "caveats": (
            "Falls back to keyword-only scoring when the embedding model is "
            "unavailable (marked in the API response). Matched keywords are shown "
            "as evidence so every score can be audited."
        ),
    },
    "alignment_gap": {
        "title": "Research Gap Flag",
        "formula": (
            "A framework pillar is flagged as a gap when its institutional average "
            "alignment score falls below the gap threshold (default 25/100)."
        ),
        "scale": "Binary flag per pillar, ranked by ascending score.",
        "source": "Derived from Framework Alignment Scores.",
        "caveats": "A gap signals low measured output, which may also reflect metadata coverage.",
    },
    "intra_african_collaboration": {
        "title": "Intra-African Collaboration Index",
        "formula": (
            "% of works whose author affiliations span ≥2 distinct African countries "
            "(full counting at the work level — the Scimago/Leiden international-"
            "collaboration indicator restricted to AU member states)."
        ),
        "scale": "0–100%.",
        "source": "OpenAlex authorship affiliations (institutions[].country_code).",
        "benchmark": {
            "value": 8.4,
            "label": "Continental average (Research Policy, 2022)",
            "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9746314/",
        },
        "caveats": (
            "Works lacking affiliation metadata are excluded from the denominator; "
            "coverage share is reported alongside the index."
        ),
    },
    "country_pair_matrix": {
        "title": "Country-Pair Collaboration Matrix",
        "formula": (
            "For each work, every unordered pair of distinct African co-author "
            "countries increments that pair's count by 1 (full counting)."
        ),
        "scale": "Raw co-publication counts per country pair.",
        "source": "OpenAlex authorship affiliations.",
        "caveats": "Counts works, not authors; a work with 3 countries contributes 3 pairs.",
    },
    "citation_velocity": {
        "title": "Citation Velocity",
        "formula": (
            "Citations accrued per calendar year from OpenAlex counts_by_year; "
            "early velocity = mean citations in the first 2 years after publication."
        ),
        "scale": "Citations/year.",
        "source": "OpenAlex counts_by_year (last 10 years, inline field).",
        "caveats": "OpenAlex citation coverage lags recent months; counts are full, not field-normalized.",
    },
    "pan_african_citation_share": {
        "title": "Pan-African Citation Share",
        "formula": (
            "% of a work's citing works that have ≥1 author affiliated with an "
            "African institution (OpenAlex group_by country of citing works)."
        ),
        "scale": "0–100% per work; institutional figure is citation-weighted mean.",
        "source": "OpenAlex cites: filter grouped by authorships.institutions.country_code.",
        "caveats": "Computed for the most-cited works first; citing works without affiliations are excluded.",
    },
    "tk_vitality": {
        "title": "TK Vitality Score",
        "formula": (
            "Weighted share of indigenous-knowledge content types: "
            "indigenous_knowledge=3.0, cultural_heritage=2.5, oral_tradition=2.5, "
            "grey_literature=1.5, thesis/dataset=1.2, patent=1.0, research_paper=0.5; "
            "normalised by total items × 3.0, scaled to 100."
        ),
        "scale": "0–100.",
        "source": "URAAS content-type classification.",
        "caveats": "Depends on content_type assignment quality at ingest.",
    },
    "linguistic_diversity": {
        "title": "Linguistic Diversity Index",
        "formula": "% of repository output published in African languages (23 ISO 639-1 codes tracked).",
        "scale": "0–100%.",
        "source": "Item language metadata (dc_language / language_code).",
        "caveats": "Language metadata is sparse in upstream sources; treat as a lower bound.",
    },
    "sc_score": {
        "title": "Special Collections Score",
        "formula": (
            "Multi-gate keyword decision engine: strong-category matches × 3 + "
            "support matches × 1, with ambiguous-token guards and STEM exclusion. "
            "Score > 0 = genuine Special Collections item."
        ),
        "scale": "0 = not SC; higher = stronger signal.",
        "source": "URAAS SC decision engine (uraas/services/sc_engine.py — open source).",
        "caveats": "All dashboard analytics are gated to SC items (score > 0) by design.",
    },
    "ark_identifier": {
        "title": "ARK Persistent Identifier",
        "formula": (
            "ark:/<NAAN>/<shoulder><name><check> minted deterministically from the "
            "item's DocID hash, betanumeric alphabet, NCDA check character."
        ),
        "scale": "—",
        "source": "ARK Alliance specification (arks.org); Africa PID Alliance × ARK Alliance partnership (2025).",
        "caveats": "Test NAAN (99999) until the production NAAN registration completes; ARKs are free to mint.",
    },
    "sc_thematic_composition": {
        "title": "Thematic Composition",
        "formula": (
            "Count of Special Collections items tagged with each of the 8 SC "
            "themes (Indigenous Knowledge, African Literature, Cultural Heritage, "
            "Ethnic Languages & Groups, Postcolonial Studies, Pan-African Studies, "
            "African Philosophy, Ethnomusicology). Items are multi-themed, so "
            "shares sum to more than 100%."
        ),
        "scale": "Item counts per theme.",
        "source": "URAAS SC decision engine categories (special_collection_categories).",
        "caveats": "An item tagged with N themes contributes to all N counts.",
    },
    "sc_cooccurrence": {
        "title": "Theme Co-occurrence",
        "formula": (
            "For each SC item, every unordered pair of its distinct themes "
            "increments that pair's link weight by 1 (full counting); single-theme "
            "items contribute to the diagonal. Visualised as a chord diagram so "
            "interdisciplinary overlaps (e.g. Indigenous Knowledge ↔ Cultural "
            "Heritage) are legible — a view commercial bibliometric tools omit."
        ),
        "scale": "Co-occurrence counts per theme pair.",
        "source": "Derived from special_collection_categories.",
        "caveats": "Reflects classifier theme assignment; sparse themes show few links.",
    },
    "sc_knowledge_sovereignty": {
        "title": "Knowledge Sovereignty",
        "formula": (
            "Distribution of contributing African countries across SC works "
            "(from co-author affiliations), plus the share of SC works spanning "
            "≥2 African countries. A custodianship lens that centres African "
            "authorship rather than North-export citation prestige."
        ),
        "scale": "Country item counts; intra-African share 0–100%.",
        "source": "OpenAlex authorship affiliations (coauthor_countries, is_intra_african).",
        "caveats": "Works without affiliation metadata are excluded from country/intra-African figures.",
    },
    "sc_sdg_alignment": {
        "title": "SDG & Development Alignment",
        "formula": (
            "Count of SC works tagged with each UN Sustainable Development Goal "
            "(works may carry multiple SDG tags), connecting cultural and "
            "indigenous-knowledge scholarship to development relevance."
        ),
        "scale": "Item counts per SDG (1–17).",
        "source": "URAAS SDG tagging (sdg_tags).",
        "caveats": "Multi-tagged works count toward each of their SDGs; tagging coverage is partial.",
    },
    "sc_influential_works": {
        "title": "Most Influential Works",
        "formula": (
            "SC works ranked by total citations received (OpenAlex cited_by_count). "
            "Used as a reach signal alongside the sovereignty and SDG lenses, not "
            "as the sole measure of value."
        ),
        "scale": "Total citations per work.",
        "source": "OpenAlex cited_by_count.",
        "caveats": "Citation coverage lags recent works; counts are full, not field-normalized.",
    },
}
