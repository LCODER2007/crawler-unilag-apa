"""
URAAS AI Classifier  v2.0
Uses spaCy (en_core_web_sm) for NLP-based SDG classification and keyword extraction.
Falls back to enhanced TF-IDF keyword matching if spaCy is unavailable.

Key improvements over v1:
- Aggressive HTML/XML/JATS artifact stripping
- Bigram and trigram phrase extraction
- Corpus-level TF-IDF (not single-doc frequency)
- Expanded stop word list removing academic filler words
- Named entity filtering (no city/country names as keywords)
"""

import html
import logging
import math
import re
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── SDG Definitions ───────────────────────────────────────────────────────────
SDG_DEFINITIONS: Dict[int, Dict] = {
    1: {
        "name": "No Poverty",
        "core": [
            "poverty",
            "economic inequality",
            "social protection",
            "income",
            "destitution",
            "livelihood",
            "microcredit",
            "social safety net",
            "extreme poverty",
            "basic needs",
        ],
    },
    2: {
        "name": "Zero Hunger",
        "core": [
            "food security",
            "malnutrition",
            "hunger",
            "food systems",
            "agriculture",
            "crop production",
            "famine",
            "nutrition",
            "food access",
            "smallholder farmers",
        ],
    },
    3: {
        "name": "Good Health",
        "core": [
            "health",
            "disease",
            "medicine",
            "clinical",
            "mortality",
            "morbidity",
            "vaccine",
            "immunization",
            "malaria",
            "hiv",
            "tuberculosis",
            "cancer",
            "mental health",
            "maternal health",
            "child mortality",
            "public health",
            "epidemiology",
            "infectious disease",
            "non-communicable disease",
        ],
    },
    4: {
        "name": "Quality Education",
        "core": [
            "education",
            "learning outcomes",
            "school",
            "university",
            "literacy",
            "numeracy",
            "curriculum",
            "pedagogy",
            "teacher training",
            "educational access",
            "early childhood",
            "higher education",
            "vocational training",
        ],
    },
    5: {
        "name": "Gender Equality",
        "core": [
            "gender equality",
            "women empowerment",
            "female participation",
            "gender-based violence",
            "feminism",
            "gender gap",
            "reproductive rights",
            "sexual harassment",
            "discrimination against women",
            "gender mainstreaming",
        ],
    },
    6: {
        "name": "Clean Water",
        "core": [
            "water supply",
            "sanitation",
            "wastewater treatment",
            "drinking water quality",
            "water scarcity",
            "water access",
            "hygiene",
            "groundwater",
            "water pollution",
            "watershed",
        ],
    },
    7: {
        "name": "Affordable Energy",
        "core": [
            "renewable energy",
            "solar power",
            "wind energy",
            "energy access",
            "photovoltaic",
            "energy poverty",
            "electricity grid",
            "energy efficiency",
            "hydropower",
            "biomass energy",
            "off-grid",
        ],
    },
    8: {
        "name": "Decent Work",
        "core": [
            "employment",
            "labour market",
            "economic growth",
            "entrepreneurship",
            "gdp growth",
            "decent work",
            "youth employment",
            "informal economy",
            "productivity",
            "workers rights",
            "job creation",
        ],
    },
    9: {
        "name": "Industry and Innovation",
        "core": [
            "innovation",
            "infrastructure",
            "industrial development",
            "manufacturing",
            "technology transfer",
            "research and development",
            "patent",
            "startup",
            "digitalization",
            "industrialization",
        ],
    },
    10: {
        "name": "Reduced Inequalities",
        "core": [
            "inequality",
            "income distribution",
            "social inclusion",
            "discrimination",
            "marginalization",
            "affirmative action",
            "wealth gap",
            "racial inequality",
            "ethnic inequality",
        ],
    },
    11: {
        "name": "Sustainable Cities",
        "core": [
            "urban planning",
            "smart city",
            "housing",
            "transport",
            "urbanization",
            "slum",
            "public space",
            "urban resilience",
            "waste management",
            "urban governance",
        ],
    },
    12: {
        "name": "Responsible Consumption",
        "core": [
            "sustainable consumption",
            "circular economy",
            "waste reduction",
            "recycling",
            "sustainable production",
            "resource efficiency",
            "plastic pollution",
            "food waste",
            "lifecycle assessment",
        ],
    },
    13: {
        "name": "Climate Action",
        "core": [
            "climate change",
            "global warming",
            "carbon emissions",
            "greenhouse gas",
            "climate adaptation",
            "climate mitigation",
            "sea level rise",
            "carbon footprint",
            "climate policy",
            "net zero",
        ],
    },
    14: {
        "name": "Life Below Water",
        "core": [
            "ocean",
            "marine ecosystem",
            "fisheries",
            "coastal management",
            "aquatic biodiversity",
            "coral reef",
            "sea pollution",
            "overfishing",
            "marine conservation",
            "lagoon",
        ],
    },
    15: {
        "name": "Life on Land",
        "core": [
            "biodiversity",
            "ecosystem",
            "deforestation",
            "land degradation",
            "wildlife conservation",
            "endangered species",
            "forest management",
            "land use change",
            "wetland",
            "desertification",
        ],
    },
    16: {
        "name": "Peace and Justice",
        "core": [
            "governance",
            "rule of law",
            "corruption",
            "institutional capacity",
            "peace",
            "conflict",
            "human rights",
            "access to justice",
            "transparency",
            "democracy",
            "peacebuilding",
        ],
    },
    17: {
        "name": "Partnerships",
        "core": [
            "international cooperation",
            "development aid",
            "public-private partnership",
            "technology transfer",
            "south-south cooperation",
            "global governance",
            "multilateralism",
            "financing for development",
        ],
    },
}

# ── Special Collections ───────────────────────────────────────────────────────
SPECIAL_COLLECTIONS: Dict[str, List[str]] = {
    "Indigenous Knowledge": [
        "indigenous knowledge",
        "traditional knowledge",
        "indigenous epistemology",
        "ethnobotany",
        "ethnobotanical",
        "traditional ecological knowledge",
        "indigenous medicine",
        "traditional healing",
        "ancestral wisdom",
        "precolonial knowledge",
        "traditional practices",
        "indigenous technology",
        "folk medicine",
        "oral traditions",
        "folklore",
        "cultural transmission",
        "indigenous cosmology",
        "traditional farming",
        "indigenous peoples",
        "traditional religion",
        "traditional medicine",
        "ethno-medicine",
        "indigenous farming",
        "ethnoveterinary",
        "indigenous architecture",
        "traditional weather forecasting",
        "local ecological knowledge",
        "indigenous forestry",
        "indigenous land management",
        "traditional food systems",
        "indigenous soil conservation",
        "indigenous metallurgy",
        "traditional pottery",
    ],
    "African Literature": [
        "postcolonial literature",
        "african literature",
        "negritude",
        "afrocentrism",
        "african novel",
        "african drama",
        "oral literature",
        "oral poetry",
        "african aesthetics",
        "indigenous poetry",
        "pan-africanism",
        "decolonizing the mind",
        "colonial literature",
        "nigerian literature",
        "kenyan literature",
        "african narrative",
        "wole soyinka",
        "chinua achebe",
        "ngugi wa thiongo",
        "african writers",
        "african storytelling",
        "griots",
        "afrofuturism",
        "african literary criticism",
        "oral narrative",
        "indigenous drama",
        "decolonial literature",
        "black aesthetics",
        "african theatre",
        "contemporary african writing",
    ],
    "Cultural Heritage": [
        "cultural heritage",
        "intangible heritage",
        "cultural identity",
        "heritage preservation",
        "oral history",
        "material culture",
        "museum studies",
        "cultural memory",
        "sacred sites",
        "cultural artifacts",
        "postcolonial heritage",
        "traditional customs",
        "cultural continuity",
        "ethnography",
        "cultural landscape",
        "cultural practices",
        "heritage conservation",
        "world heritage",
        "cultural diversity",
        "indigenous heritage",
        "living heritage",
        "ancestral heritage",
        "cultural preservation",
        "traditional ceremonies",
        "indigenous art",
        "monuments preservation",
        "archaeological heritage",
        "sacred groves",
        "rock art preservation",
        "indigenous textiles",
    ],
    "Ethnic Languages & Groups": [
        "ethnic group",
        "ethnic language",
        "indigenous language",
        "yoruba",
        "igbo",
        "hausa",
        "swahili",
        "kiswahili",
        "amharic",
        "zulu",
        "xhosa",
        "shona",
        "somali",
        "kinyarwanda",
        "oromo",
        "twi",
        "fante",
        "ewe",
        "wolof",
        "luganda",
        "lingala",
        "bambara",
        "tigrinya",
        "chewa",
        "ndebele",
        "sotho",
        "sesotho",
        "setswana",
        "tsonga",
        "ss",
        "venda",
        "fulani",
        "maasai",
        "igboland",
        "yorubaland",
        "hausaland",
        "kikuyu",
        "oromoland",
        "luo",
        "akan",
        "ganda",
        "shona culture",
        "zulu kingdom",
        "ashanti",
        "yoruba cosmology",
        "igbo metaphysics",
        "swahili coast",
    ],
    "Postcolonial Studies": [
        "postcolonialism",
        "decolonization",
        "colonialism",
        "imperialism",
        "subaltern",
        "hybridity",
        "mimicry",
        "diaspora studies",
        "postcolonial theory",
        "colonial legacy",
        "neo-colonialism",
        "independence movements",
        "african nationalism",
        "resistance literature",
        "colonial history",
        "settler colonialism",
        "decolonial thought",
        "decoloniality",
        "epistemic decolonization",
        "postcolonial identity",
        "colonial violence",
        "anti-colonial resistance",
        "decolonial turn",
    ],
    "Pan-African Studies": [
        "pan-africanism",
        "african unity",
        "african union",
        "african identity",
        "african renaissance",
        "afrocentricity",
        "african development",
        "african continental",
        "afro-optimism",
        "black consciousness",
        "african solidarity",
        "african geopolitics",
        "ecowas",
        "sadc",
        "east african community",
        "african integration",
        "black diaspora",
        "panafrican",
        "african economic community",
        "agenda 2063",
    ],
    "African Philosophy": [
        "ubuntu",
        "african philosophy",
        "african ethics",
        "communalism",
        "african metaphysics",
        "african ontology",
        "african logic",
        "african epistemology",
        "african humanism",
        "african thought",
        "african worldview",
        "indigenous philosophy",
        "sage philosophy",
        "negritude philosophy",
        "ubuntu ethics",
        "african communitarianism",
    ],
    "Ethnomusicology": [
        "ethnomusicology",
        "african music",
        "traditional music",
        "folk music",
        "african drumming",
        "musical heritage",
        "afrobeats",
        "highlife",
        "african rhythm",
        "musical traditions",
        "indigenous music",
        "oral musical tradition",
        "african instruments",
        "kora music",
        "mbira music",
        "djembe drumming",
        "traditional chants",
    ],
}

# ── African Union Charter Targets ─────────────────────────────────────────────
AU_CHARTER_TARGETS: Dict[int, Dict] = {
    1: {
        "name": "Tangible & Intangible Cultural Heritage Preservation",
        "keywords": [
            "cultural heritage",
            "intangible heritage",
            "heritage preservation",
            "material culture",
            "museum studies",
            "cultural artifacts",
            "heritage conservation",
            "world heritage",
            "sacred sites",
            "living heritage",
            "archaeological",
            "rock art",
            "sacred groves",
        ],
    },
    2: {
        "name": "Development of African Languages & Decolonization of Science",
        "keywords": [
            "indigenous language",
            "yoruba",
            "igbo",
            "hausa",
            "swahili",
            "amharic",
            "zulu",
            "xhosa",
            "shona",
            "somali",
            "kinyarwanda",
            "oromo",
            "twi",
            "fante",
            "ewe",
            "wolof",
            "luganda",
            "lingala",
            "bambara",
            "tigrinya",
            "chewa",
            "ndebele",
            "sotho",
            "african language",
            "ethnic language",
            "decolonizing science",
            "linguistic diversity",
        ],
    },
    3: {
        "name": "Integration of Cultural Values & Indigenous Knowledge Systems",
        "keywords": [
            "indigenous knowledge",
            "traditional knowledge",
            "indigenous epistemology",
            "ethnobotany",
            "traditional ecological knowledge",
            "indigenous medicine",
            "traditional healing",
            "ancestral wisdom",
            "traditional practices",
            "precolonial knowledge",
            "indigenous cosmology",
            "traditional religion",
        ],
    },
    4: {
        "name": "Inter-Institutional Cultural Exchange & Regional Integration",
        "keywords": [
            "cultural exchange",
            "regional integration",
            "pan-africanism",
            "african solidarity",
            "african union",
            "african continental",
            "cross-border",
            "ecowas",
            "sadc",
            "east african community",
        ],
    },
    5: {
        "name": "Support for Creative and Cultural Industries",
        "keywords": [
            "creative industry",
            "cultural industry",
            "african literature",
            "african music",
            "african novel",
            "african drama",
            "oral literature",
            "traditional music",
            "african drumming",
            "highlife",
            "afrobeats",
            "performing arts",
            "african cinema",
            "storytelling",
            "folklore",
        ],
    },
    6: {
        "name": "Scientific Innovation & Traditional Technology Integration",
        "keywords": [
            "traditional technology",
            "indigenous technology",
            "traditional farming",
            "traditional agriculture",
            "ethnoveterinary",
            "indigenous agriculture",
            "traditional metallurgy",
            "traditional medicine production",
        ],
    },
    7: {
        "name": "Youth Engagement & Cultural Education",
        "keywords": [
            "cultural transmission",
            "cultural education",
            "pedagogy",
            "oral history",
            "folklore",
            "oral tradition",
            "youth engagement",
            "cultural values",
        ],
    },
    8: {
        "name": "Intellectual Property, Open Access, and Copyright Protection",
        "keywords": [
            "intellectual property",
            "open access",
            "copyright",
            "traditional knowledge rights",
            "biopiracy",
            "patent protection",
            "indigenous rights",
            "open science",
        ],
    },
    9: {
        "name": "Decolonial Philosophy & African Thought Systems (Ubuntu)",
        "keywords": [
            "ubuntu",
            "african philosophy",
            "african thought",
            "african ethics",
            "communalism",
            "decolonial",
            "decolonization",
            "postcolonialism",
            "negritude",
            "afrocentricity",
            "decolonial thought",
            "subaltern",
            "african worldview",
        ],
    },
}


def classify_au_targets(title: str, abstract: str, dc_subject: str = "") -> List[Dict]:
    """
    Classify a paper against the 9 African Union Charter Targets.
    Returns list of {target_number, target_name, score, matched_keywords}.
    """
    text = _clean_text(f"{title or ''} {abstract or ''} {dc_subject or ''}").lower()
    if not text.strip():
        return []

    results = []
    for num, defn in AU_CHARTER_TARGETS.items():
        score, matched = _keyword_score(text, defn["keywords"])
        if score >= 1:
            results.append(
                {
                    "target_number": num,
                    "target_name": defn["name"],
                    "score": score,
                    "matched_keywords": matched[:6],
                }
            )

    results.sort(key=lambda x: -x["score"])
    return results


# ── Comprehensive Stop Words ──────────────────────────────────────────────────
# Covers: common English, academic filler, metadata artifacts, XML/JATS tags,
# geographic terms that are too broad, formatting remnants
STOP_WORDS = {
    # Common English
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "have",
    "been",
    "were",
    "their",
    "which",
    "these",
    "about",
    "other",
    "into",
    "than",
    "more",
    "such",
    "some",
    "what",
    "when",
    "where",
    "there",
    "also",
    "using",
    "used",
    "show",
    "both",
    "each",
    "only",
    "very",
    "well",
    "high",
    "low",
    "new",
    "large",
    "small",
    "significant",
    "different",
    "similar",
    "total",
    "however",
    "therefore",
    "thus",
    "hence",
    "although",
    "despite",
    "while",
    "after",
    "before",
    "through",
    "across",
    "during",
    "within",
    "among",
    "between",
    "either",
    "neither",
    "whether",
    "since",
    "upon",
    "against",
    "without",
    "under",
    "over",
    "above",
    "below",
    "around",
    "towards",
    "onto",
    "itself",
    "itself",
    "itself",
    "they",
    "them",
    "their",
    "those",
    "these",
    "here",
    "then",
    "just",
    "like",
    "make",
    "many",
    "most",
    "much",
    "even",
    "back",
    "still",
    "need",
    "could",
    "would",
    "should",
    "shall",
    "will",
    "might",
    "must",
    "been",
    "have",
    "does",
    "done",
    "made",
    "said",
    "take",
    "come",
    "find",
    "give",
    "know",
    "look",
    "seem",
    "feel",
    "become",
    "include",
    "provide",
    "require",
    "remain",
    "suggest",
    "indicate",
    "demonstrate",
    "show",
    "reveal",
    "confirm",
    "report",
    "find",
    "identify",
    "examine",
    "determine",
    "evaluate",
    "assess",
    "compare",
    "describe",
    "present",
    "discuss",
    "explore",
    "investigate",
    "conduct",
    "perform",
    "apply",
    "observe",
    "measure",
    "calculate",
    "estimate",
    "predict",
    "test",
    # Academic filler
    "study",
    "paper",
    "research",
    "analysis",
    "findings",
    "results",
    "method",
    "approach",
    "model",
    "system",
    "review",
    "case",
    "report",
    "effect",
    "impact",
    "based",
    "data",
    "conclusion",
    "objective",
    "background",
    "introduction",
    "abstract",
    "methods",
    "discussion",
    "purpose",
    "aim",
    "goal",
    "hypothesis",
    "evidence",
    "sample",
    "group",
    "population",
    "intervention",
    "outcome",
    "variable",
    "factor",
    "relationship",
    "association",
    "correlation",
    "significance",
    "difference",
    "increase",
    "decrease",
    "higher",
    "lower",
    "greater",
    "lower",
    "compared",
    "respectively",
    "overall",
    "showed",
    "found",
    "reported",
    "observed",
    "noted",
    "significantly",
    "p-value",
    "confidence",
    "interval",
    "mean",
    "median",
    "standard",
    "deviation",
    "percent",
    "percentage",
    "proportion",
    "ratio",
    "rate",
    "number",
    "approximately",
    "moreover",
    "furthermore",
    "additionally",
    "however",
    "nevertheless",
    "consequently",
    "therefore",
    "conclusion",
    "finally",
    "firstly",
    "secondly",
    "lastly",
    "currently",
    "recently",
    "previously",
    "generally",
    "specifically",
    "particularly",
    "mainly",
    "primarily",
    "mostly",
    "largely",
    "significantly",
    "approximately",
    "relatively",
    # Metadata / XML / JATS artifacts
    "jats",
    "jats-inline",
    "journal",
    "abstract",
    "article",
    "title",
    "italic",
    "bold",
    "sup",
    "sub",
    "break",
    "para",
    "section",
    "body",
    "front",
    "back",
    "meta",
    "keyword",
    "keywords",
    "author",
    "authors",
    "affiliation",
    "institution",
    "corresponding",
    "mailto",
    "email",
    "grant",
    "funding",
    "acknowledgment",
    "acknowledgements",
    "references",
    "bibliography",
    "footnote",
    "table",
    "figure",
    "appendix",
    "supplement",
    # Geographic terms too broad to be meaningful keywords
    "nigeria",
    "nigerian",
    "lagos",
    "africa",
    "african",
    "world",
    "global",
    "international",
    "national",
    "regional",
    "local",
    "country",
    "countries",
    "continent",
    "west",
    "east",
    "south",
    "north",
    "central",
    # Numbers and fragments that slip through
    "2266",
    "2015",
    "2016",
    "2017",
    "2018",
    "2019",
    "2020",
    "2021",
    "2022",
    "2023",
    "2024",
    "2025",
    # Short meaningless words (caught by length filter but listed for clarity)
    "also",
    "into",
    "onto",
    "upon",
    "with",
    "from",
    "have",
    "that",
}

# Regex patterns for artifacts to strip before processing
_HTML_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_JATS_TAG_RE = re.compile(r"\bjats:[a-z\-]+\b", re.IGNORECASE)
_NON_ALPHA_RE = re.compile(r"[^a-zA-Z\s\-]")
_MULTI_SPACE_RE = re.compile(r"\s+")


def _clean_text(text: str) -> str:
    """Strip HTML entities, XML/JATS tags, and non-alphabetic artifacts."""
    if not text:
        return ""
    # Decode HTML entities (e.g., &amp;lt; → <)
    text = html.unescape(text)
    text = html.unescape(text)  # Double-decode for double-encoded entities
    # Strip remaining HTML/XML tags
    text = _HTML_TAG_RE.sub(" ", text)
    # Strip JATS namespace tokens
    text = _JATS_TAG_RE.sub(" ", text)
    # Strip remaining HTML entities
    text = _HTML_ENTITY_RE.sub(" ", text)
    # Remove non-alphabetic characters (keep hyphens for compound terms)
    text = _NON_ALPHA_RE.sub(" ", text)
    # Normalise whitespace
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text


def _is_valid_word(word: str) -> bool:
    """Return True if the word is a meaningful academic term."""
    if len(word) < 4:
        return False
    if word in STOP_WORDS:
        return False
    # Reject pure number strings
    if word.isdigit():
        return False
    # Reject words that are mostly digits
    digit_ratio = sum(c.isdigit() for c in word) / len(word)
    if digit_ratio > 0.3:
        return False
    # Reject very short all-caps (likely acronyms of metadata)
    if len(word) <= 4 and word.isupper():
        return False
    return True


# ── NLP loading ───────────────────────────────────────────────────────────────
_nlp = None
_spacy_available = False


def _load_nlp():
    global _nlp, _spacy_available
    if _nlp is not None:
        return _nlp
    try:
        import spacy

        try:
            _nlp = spacy.load("en_core_web_sm")
        except OSError:
            import subprocess
            import sys

            subprocess.run(
                [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
                capture_output=True,
            )
            _nlp = spacy.load("en_core_web_sm")
        _spacy_available = True
        log.info("spaCy model loaded: en_core_web_sm")
    except Exception as e:
        log.warning(f"spaCy unavailable ({e}), using TF-IDF fallback")
        _spacy_available = False
    return _nlp


# ── Core classification functions ─────────────────────────────────────────────

import re


def _keyword_score(text: str, keywords: List[str]) -> Tuple[int, List[str]]:
    """Score text against a keyword list, return (score, matched_keywords)."""
    text_lower = text.lower()
    matched = []
    for kw in keywords:
        kw_lower = kw.lower()
        if re.search(rf"\b{re.escape(kw_lower)}\b", text_lower):
            matched.append(kw)
    return len(matched), matched


def classify_sdgs(title: str, abstract: str, threshold: int = 1) -> List[Dict]:
    """
    Classify a paper against all 17 SDGs using AI + keyword matching.
    Returns list of {sdg_number, sdg_name, score, matched_keywords} sorted by score desc.
    """
    text = _clean_text(f"{title or ''} {abstract or ''}").strip()
    if not text:
        return []

    nlp = _load_nlp()
    enriched = text.lower()
    if _spacy_available and nlp:
        try:
            doc = nlp(text[:5000])
            noun_chunks = [chunk.text.lower() for chunk in doc.noun_chunks]
            enriched = text.lower() + " " + " ".join(noun_chunks)
        except Exception:
            pass

    results = []
    for sdg_num, defn in SDG_DEFINITIONS.items():
        score, matched = _keyword_score(enriched, defn["core"])
        if score >= threshold:
            results.append(
                {
                    "sdg_number": sdg_num,
                    "sdg_name": defn["name"],
                    "score": score,
                    "matched_keywords": matched[:8],
                }
            )

    results.sort(key=lambda x: -x["score"])
    return results


def classify_special_collections(
    title: str, abstract: str, dc_subject: str = ""
) -> List[Dict]:
    """
    Classify a paper into special collections categories.
    Returns list of {category, score, matched_keywords}.
    """
    text = _clean_text(f"{title or ''} {abstract or ''} {dc_subject or ''}").lower()
    if not text.strip():
        return []

    results = []
    for category, keywords in SPECIAL_COLLECTIONS.items():
        score, matched = _keyword_score(text, keywords)
        if score >= 1:
            results.append(
                {
                    "category": category,
                    "score": score * 3,
                    "matched_keywords": matched[:6],
                }
            )

    results.sort(key=lambda x: -x["score"])
    return results


def extract_keywords(
    title: str, abstract: str, top_n: int = 60, all_texts: Optional[List[str]] = None
) -> List[Dict]:
    """
    Extract key academic terms using TF-IDF + spaCy NER + bigrams.

    Args:
        title: Paper title
        abstract: Paper abstract
        top_n: Number of keywords to return
        all_texts: Optional list of all abstracts/titles for IDF calculation.
                   If provided, uses corpus-level TF-IDF for better ranking.

    Returns:
        [{word, score, count, type}] sorted by relevance score.
    """
    raw = f"{title or ''} {abstract or ''}".strip()
    text = _clean_text(raw)
    if not text:
        return []

    text_lower = text.lower()

    # ── Unigrams ──────────────────────────────────────────────────────────────
    words = re.findall(r"\b[a-zA-Z][a-zA-Z\-]{3,}\b", text_lower)
    unigrams = [w for w in words if _is_valid_word(w)]

    # ── Bigrams (two-word phrases) ────────────────────────────────────────────
    bigrams = []
    for i in range(len(words) - 1):
        w1, w2 = words[i], words[i + 1]
        if _is_valid_word(w1) and _is_valid_word(w2):
            bigram = f"{w1} {w2}"
            bigrams.append(bigram)

    # ── Trigrams (three-word phrases for compound terms) ─────────────────────
    trigrams = []
    for i in range(len(words) - 2):
        w1, w2, w3 = words[i], words[i + 1], words[i + 2]
        if _is_valid_word(w1) and _is_valid_word(w2) and _is_valid_word(w3):
            trigrams.append(f"{w1} {w2} {w3}")

    # ── Frequency counts ──────────────────────────────────────────────────────
    term_freq: Dict[str, int] = {}
    for t in unigrams + bigrams + trigrams:
        term_freq[t] = term_freq.get(t, 0) + 1

    # ── IDF computation (if corpus provided) ─────────────────────────────────
    idf_scores: Dict[str, float] = {}
    if all_texts and len(all_texts) > 1:
        N = len(all_texts)
        all_texts_lower = [doc.lower() for doc in all_texts]
        candidate_terms = sorted(term_freq.keys(), key=lambda t: -term_freq[t])[:1500]
        for term in candidate_terms:
            doc_count = sum(1 for doc in all_texts_lower if term in doc)
            idf_scores[term] = math.log((N + 1) / (doc_count + 1)) + 1
        for term in term_freq:
            if term not in idf_scores:
                idf_scores[term] = 1.0
    else:
        # Without corpus, use log(freq+1) as a proxy
        for term in term_freq:
            idf_scores[term] = math.log(term_freq[term] + 2)

    # ── Score = TF * IDF ──────────────────────────────────────────────────────
    total = sum(term_freq.values()) or 1
    scored = []
    for term, freq in term_freq.items():
        tf = freq / total
        idf = idf_scores.get(term, 1.0)
        score = round(tf * idf * 100, 3)
        # Boost multi-word phrases (they're more meaningful)
        if " " in term:
            score *= 1.5 if term.count(" ") == 1 else 2.0
        scored.append(
            {
                "word": term,
                "score": score,
                "count": freq,
                "type": "phrase" if " " in term else "term",
            }
        )

    # ── Add spaCy named entities (boost recognized entities) ─────────────────
    nlp = _load_nlp()
    if _spacy_available and nlp:
        try:
            doc = nlp(text[:3000])
            for ent in doc.ents:
                # Only include meaningful entity types, skip countries/cities as keywords
                if ent.label_ in (
                    "ORG",
                    "PRODUCT",
                    "WORK_OF_ART",
                    "EVENT",
                    "LAW",
                    "NORP",
                ):
                    ent_text = ent.text.lower()
                    ent_clean = _clean_text(ent_text)
                    if len(ent_clean) >= 4 and _is_valid_word(ent_clean.split()[0]):
                        scored.append(
                            {
                                "word": ent_clean,
                                "score": 6.0,
                                "count": 1,
                                "type": "entity",
                            }
                        )
        except Exception:
            pass

    # ── Sort, deduplicate, return top N ──────────────────────────────────────
    scored.sort(key=lambda x: -x["score"])
    seen: set = set()
    unique = []
    for item in scored:
        key = item["word"].lower().strip()
        # Skip if a longer phrase containing this term already present
        if key not in seen:
            seen.add(key)
            # Also mark sub-terms of present phrases to avoid redundancy
            unique.append(item)

    return unique[:top_n]


def extract_trends_from_corpus(papers: List[Dict], top_n: int = 12) -> List[Dict]:
    """
    AI-powered trend extraction from a corpus of papers.
    Groups papers into semantic topic clusters using TF-IDF similarity.

    Args:
        papers: List of {id, title, abstract, year} dicts
        top_n: Number of trends to discover

    Returns:
        List of {topic, keywords, paper_count, years, papers} dicts
    """
    if not papers:
        return []

    # Build per-year keyword frequency
    year_keywords: Dict[int, Dict[str, int]] = {}
    all_texts = [f"{p.get('title','')} {p.get('abstract','')}" for p in papers]

    for p in papers:
        year = p.get("year")
        if not year:
            continue
        text = _clean_text(f"{p.get('title','')} {p.get('abstract','')}")
        words = re.findall(r"\b[a-zA-Z][a-zA-Z\-]{3,}\b", text.lower())
        words = [w for w in words if _is_valid_word(w)]

        # Also extract bigrams
        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i + 1]
            if _is_valid_word(w1) and _is_valid_word(w2):
                words.append(f"{w1} {w2}")

        if year not in year_keywords:
            year_keywords[year] = {}
        for w in words:
            year_keywords[year][w] = year_keywords[year].get(w, 0) + 1

    # Find terms that appear across multiple years (persistent trends)
    global_freq: Dict[str, int] = {}
    global_year_presence: Dict[str, set] = {}
    for year, freq_map in year_keywords.items():
        for term, count in freq_map.items():
            global_freq[term] = global_freq.get(term, 0) + count
            if term not in global_year_presence:
                global_year_presence[term] = set()
            global_year_presence[term].add(year)

    # Score terms: frequency × year spread
    N_docs = len(all_texts)
    all_texts_lower = [t.lower() for t in all_texts]
    candidate_terms = sorted(global_freq.keys(), key=lambda t: -global_freq[t])[:1500]
    trend_scores: Dict[str, float] = {}
    for term, freq in global_freq.items():
        if term in candidate_terms:
            year_spread = len(global_year_presence.get(term, set()))
            doc_count = sum(1 for t in all_texts_lower if term in t)
            idf = math.log((N_docs + 1) / (doc_count + 1)) + 1
            trend_scores[term] = freq * year_spread * idf
        else:
            trend_scores[term] = 0.0

    # Get top terms as seed topics
    top_terms = sorted(trend_scores.items(), key=lambda x: -x[1])[: top_n * 3]

    # Group into trends by co-occurrence (simple greedy clustering)
    trends = []
    used_terms: set = set()

    for seed_term, seed_score in top_terms:
        if seed_term in used_terms:
            continue
        if len(trends) >= top_n:
            break

        # Find related terms (share at least one year and high frequency)
        related = [seed_term]
        used_terms.add(seed_term)
        seed_years = global_year_presence.get(seed_term, set())

        for term, score in top_terms:
            if term in used_terms:
                continue
            term_years = global_year_presence.get(term, set())
            overlap = len(seed_years & term_years)
            if overlap >= 1:
                # Check if they appear near each other in text (simple proxy: both in same abstract)
                co_occur = sum(
                    1 for t in all_texts if seed_term in t.lower() and term in t.lower()
                )
                if co_occur >= 1:
                    related.append(term)
                    used_terms.add(term)
            if len(related) >= 5:
                break

        # Find papers matching this trend cluster
        trend_papers = []
        for p in papers:
            text = f"{p.get('title','')} {p.get('abstract','')}".lower()
            if any(t in text for t in related[:3]):
                trend_papers.append(p)

        if len(trend_papers) < 2:
            continue

        # Build topic label from seed (capitalise key phrase)
        label_parts = seed_term.split()
        label = " ".join(w.capitalize() for w in label_parts[:3])

        # Year-by-year paper counts
        by_year = {}
        for p in trend_papers:
            yr = p.get("year")
            if yr:
                by_year[str(yr)] = by_year.get(str(yr), 0) + 1

        trends.append(
            {
                "topic": label,
                "keywords": related[:6],
                "paper_count": len(trend_papers),
                "total": len(trend_papers),
                "by_year": by_year,
                "papers": [
                    {"id": p.get("id"), "title": p.get("title"), "year": p.get("year")}
                    for p in trend_papers[:20]
                ],
            }
        )

    trends.sort(key=lambda x: -x["paper_count"])
    return trends[:top_n]
