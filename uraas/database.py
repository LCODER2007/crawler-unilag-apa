"""
URAAS Database Models
Supports the APA Intelligence & Analytics Platform:
- Dublin Core metadata (DSpace-compatible)
- DocID™ persistent identifiers (Africa PID Alliance)
- ORCID / ROR integration
- TK (Traditional Knowledge) labels for indigenous content
- Linguistic metadata for Diversity Index
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer
from sqlalchemy import String
from sqlalchemy import String as SAString
from sqlalchemy import Table, Text, cast, create_engine, extract, func
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from uraas.config import config


# Cache the dialect at import time — URL cannot change at runtime.
_IS_SQLITE: bool = (config.DATABASE_URL or "").lower().startswith("sqlite")


def db_year(col):
    """Cross-dialect YEAR() extraction returning a string ('2024').

    SQLite has no extract(year) for TEXT-stored datetimes when the column
    was populated from ISO strings, so we use strftime there. Postgres
    rejects strftime, so we use extract(year).
    """
    if _IS_SQLITE:
        return func.strftime("%Y", col)
    return cast(extract("year", col), SAString)


def db_year_month(col):
    """Cross-dialect YEAR-MONTH ('2024-03')."""
    if _IS_SQLITE:
        return func.strftime("%Y-%m", col)
    return func.to_char(col, "YYYY-MM")


Base = declarative_base()

# ── Association Tables ────────────────────────────────────────────────────────

item_authors = Table(
    "item_authors",
    Base.metadata,
    Column(
        "item_id", Integer, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "author_id",
        Integer,
        ForeignKey("authors.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

item_collections = Table(
    "item_collections",
    Base.metadata,
    Column(
        "item_id", Integer, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "collection_id",
        Integer,
        ForeignKey("collections.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("confidence_score", Float, default=1.0),
)

# ── Core Models ───────────────────────────────────────────────────────────────


class Community(Base):
    """Faculty / School — top-level organisational unit."""

    __tablename__ = "communities"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)

    # ── APA / ROR ─────────────────────────────────────────────────────────────
    ror_id = Column(String(128))  # e.g. https://ror.org/03qcnxw14
    institution = Column(String(255))  # parent institution name
    ror = Column(String(128))  # Institution ROR for multi-tenant comparison

    collections = relationship("Collection", back_populates="community")


class Collection(Base):
    """Department / Research Group — second-level unit."""

    __tablename__ = "collections"

    id = Column(Integer, primary_key=True)
    community_id = Column(Integer, ForeignKey("communities.id"), nullable=False)
    name = Column(String(255), unique=True, nullable=False)
    email_domains = Column(Text)  # comma-separated
    keywords = Column(Text)  # comma-separated

    community = relationship("Community", back_populates="collections")
    items = relationship(
        "Item", secondary=item_collections, back_populates="collections"
    )


class Author(Base):
    """Researcher / Creator."""

    __tablename__ = "authors"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    normalized_name = Column(String(255), nullable=False, index=True)
    profile_url = Column(String(512))

    # PID integrations
    orcid = Column(String(64))  # e.g. 0000-0002-1825-0097
    ror = Column(String(128))  # institutional ROR

    items = relationship("Item", secondary=item_authors, back_populates="authors")


class Item(Base):
    """
    Research output — paper, thesis, dataset, cultural artefact, etc.
    Stores full Dublin Core + DocID™ + APA-specific metadata.
    """

    __tablename__ = "items"

    id = Column(Integer, primary_key=True)
    title = Column(String(512), nullable=False)
    abstract = Column(Text)
    doi = Column(String(255), unique=True)
    publication_date = Column(DateTime)
    url = Column(String(512), unique=True)
    source_repository = Column(String(100))
    pdf_url = Column(String(512))

    # ── Dublin Core ───────────────────────────────────────────────────────────
    dc_title = Column(String(512))
    dc_date_issued = Column(String(50))
    dc_identifier_uri = Column(String(512))
    dc_identifier_doi = Column(String(255))
    dc_description_provenance = Column(Text)
    dc_rights = Column(String(255), default="info:eu-repo/semantics/restrictedAccess")
    dc_type = Column(String(100))  # Article, Thesis, Dataset, CulturalHeritage …
    dc_language = Column(String(50))  # ISO 639-1 code, e.g. "en", "yo", "ig"
    dc_subject = Column(Text)  # comma-separated subject tags

    # ── DocID™ (Africa PID Alliance) ─────────────────────────────────────────
    docid = Column(String(128), unique=True, index=True)  # 20.500.14351/[hash]
    docid_assigned_at = Column(DateTime)

    # ── APA-specific fields ───────────────────────────────────────────────────
    # Institution ROR for multi-tenant comparison
    ror = Column(String(128), index=True)  # e.g. https://ror.org/03qcnxw14
    institution = Column(String(255))  # Institution name

    # Content type for TK Vitality Score
    content_type = Column(String(50), default="research_paper")
    # Values: research_paper | thesis | patent | indigenous_knowledge |
    #         cultural_heritage | oral_tradition | dataset | grey_literature

    # Traditional Knowledge labels (CARE principles)
    tk_label = Column(String(100))  # e.g. "TK Attribution", "TK Non-Commercial"
    tk_community = Column(String(255))  # originating community

    # Patent linkage (Patent-to-Paper Velocity)
    patent_id = Column(String(128))
    patent_date = Column(DateTime)

    # Language metadata (Linguistic Diversity Index)
    language_code = Column(String(10))  # ISO 639-1: "en", "yo", "ig", "ha", "sw" …
    is_african_language = Column(Boolean, default=False)

    # SDG alignment (comma-separated SDG numbers, e.g. "3,4,13")
    sdg_tags = Column(Text)

    # AI-extracted keywords (comma-separated)
    ai_keywords = Column(Text)

    # Special Collections weighting (computed by classify_special_collections).
    # score = sum of (matched_keywords * 3) across all SC categories; 0 = not SC.
    # categories = comma-separated category names with hits, e.g. "Indigenous Knowledge,Cultural Heritage".
    special_collection_score = Column(Float, default=0.0, index=True)
    special_collection_categories = Column(Text)

    # ── Framework alignment (AU charters / Agenda 2063 / regional blocs) ─────
    # JSON: {"banjul": {"overall": 42.1, "pillars": {"civil_political_rights":
    #   {"score": 61.0, "semantic": 0.55, "keyword": 0.71,
    #    "matched_keywords": ["human rights", ...]}}}, ...}
    alignment_scores = Column(Text)
    alignment_version = Column(Integer, default=0)

    # ── Intra-African collaboration (from OpenAlex authorships) ──────────────
    coauthor_countries = Column(Text)  # sorted ISO2 csv, e.g. "KE,NG,ZA"
    african_country_count = Column(Integer, default=0)
    is_intra_african = Column(Boolean, default=False, index=True)

    # ── Citation velocity (OpenAlex counts_by_year) ──────────────────────────
    openalex_id = Column(String(64))  # e.g. "W2741809807"
    counts_by_year = Column(Text)  # JSON [{"year": 2023, "cited_by_count": 4}, ...]
    cited_by_count = Column(Integer, default=0)
    african_citation_share = Column(Float)  # 0-100; NULL = not yet computed

    # ── ARK persistent identifier (Archival Resource Key) ────────────────────
    ark = Column(String(128))  # e.g. "ark:/99999/u1x7kq2m9b4cz" (unique index below)
    ark_assigned_at = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)

    authors = relationship("Author", secondary=item_authors, back_populates="items")
    collections = relationship(
        "Collection", secondary=item_collections, back_populates="items"
    )
    files = relationship("File", back_populates="item", cascade="all, delete-orphan")


class File(Base):
    """Local PDF bitstream."""

    __tablename__ = "files"

    id = Column(Integer, primary_key=True)
    item_id = Column(
        Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False
    )
    file_path = Column(String(512), nullable=False)
    sha256_hash = Column(String(128))
    access_policy = Column(String(50), default="Private")
    downloaded_at = Column(DateTime, default=datetime.utcnow)

    item = relationship("Item", back_populates="files")


class ItemAffiliation(Base):
    """One row per (item, institution) authorship affiliation from OpenAlex.

    Feeds the country-pair collaboration matrix, the Africa choropleth and
    institution-level collaboration networks.
    """

    __tablename__ = "item_affiliations"

    id = Column(Integer, primary_key=True)
    item_id = Column(
        Integer, ForeignKey("items.id", ondelete="CASCADE"), index=True, nullable=False
    )
    ror = Column(String(128), index=True)  # short form, e.g. "05rk03822"
    institution_name = Column(String(255))
    country_code = Column(String(2), index=True)  # ISO2 from OpenAlex
    author_count = Column(Integer, default=1)  # authors at this institution on this paper


class AlignmentAggregate(Base):
    """Precomputed per-institution framework/pillar alignment averages.

    Recomputed by scripts/backfill_alignment.py and the post-crawl hook;
    read directly by the radar/matrix/gap endpoints.
    """

    __tablename__ = "alignment_aggregates"

    id = Column(Integer, primary_key=True)
    institution = Column(String(255), index=True)  # full name; "" = all institutions
    framework = Column(String(64), index=True)  # e.g. "banjul", "agenda2063"
    pillar = Column(String(64))  # pillar key
    avg_score = Column(Float, default=0.0)
    paper_count = Column(Integer, default=0)  # papers with pillar score >= threshold
    top_item_ids = Column(Text)  # csv of top-5 item ids (evidence chips)
    computed_at = Column(DateTime, default=datetime.utcnow)


class CrawlJob(Base):
    """Tracks crawler sessions for provenance and growth-rate charts."""

    __tablename__ = "crawl_jobs"

    id = Column(Integer, primary_key=True)
    source_name = Column(String(100), nullable=False)
    status = Column(String(50), default="PENDING")
    items_scraped = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime)


# ── Indexes for query performance ─────────────────────────────────────────────
Index("ix_items_docid", Item.docid)
Index("ix_items_language", Item.language_code)
Index("ix_items_content_type", Item.content_type)
Index("ix_items_created_at", Item.created_at)
Index("ix_authors_orcid", Author.orcid)
Index("ux_items_ark", Item.ark, unique=True)
Index(
    "ix_item_aff_item_country",
    ItemAffiliation.item_id,
    ItemAffiliation.country_code,
)


# ── Engine & Session ──────────────────────────────────────────────────────────
def _build_engine():
    """SQLite needs check_same_thread=False; Postgres rejects that arg."""
    url = config.DATABASE_URL
    # Render exposes postgres:// but SQLAlchemy 2.x wants postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600)


engine = _build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
