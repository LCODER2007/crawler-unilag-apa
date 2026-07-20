"""
African language codes shared between spiders and the analytics engine.

Kept as a plain dict with no SQLAlchemy/spaCy import weight so a Scrapy
spider process can use it without pulling in uraas.analytics.engine (which
drags in DB sessions and NLP models a spider has no need for).
"""

AFRICAN_LANG_CODES = {
    "yo": "Yoruba",
    "ig": "Igbo",
    "ha": "Hausa",
    "sw": "Swahili",
    "am": "Amharic",
    "so": "Somali",
    "rw": "Kinyarwanda",
    "sn": "Shona",
    "zu": "Zulu",
    "xh": "Xhosa",
    "af": "Afrikaans",
    "st": "Sesotho",
    "tn": "Setswana",
    "ts": "Tsonga",
    "ss": "Swati",
    "ve": "Venda",
    "nr": "Ndebele",
    "ff": "Fula",
    "wo": "Wolof",
    "bm": "Bambara",
    "ln": "Lingala",
    "kg": "Kongo",
    "lua": "Luba",
    "om": "Oromo",
}
