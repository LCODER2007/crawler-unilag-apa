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

    # ── Unit type + self-minted PID ──────────────────────────────────────────
    # unit_type: "faculty" (default) | "ace" (Africa Centre of Excellence)
    unit_type = Column(String(30), default="faculty")
    pmd = Column(String(128))  # self-minted persistent ID (see ark_generator); unique index below
    pmd_assigned_at = Column(DateTime)

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
    isni = Column(String(20))  # e.g. 0000 0001 2103 2683

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

    # Special Collections weighting (computed by
    # uraas.services.sc_engine.is_special_collection() — NOT
    # uraas.utils.ai_classifier.classify_special_collections, an older
    # unguarded keyword-hit-count gate no longer wired to ingestion).
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

    # ── Funders (OpenAlex funders/awards, Crossref funder) ───────────────────
    # JSON [{"name": str, "ror": str|None, "award_id": str|None}, ...].
    # Feeds DOCiD publish's funders[i][name/other_name/type/country/ror_id]
    # FormData fields (see uraas/services/docid_client.py) once real
    # credentials exist. NULL/empty means no funder data was found for this
    # item, not "not yet checked" — every spider that supports extraction
    # always sets the field (possibly to "[]").
    funders = Column(Text)

    # ── ARK persistent identifier (Archival Resource Key) ────────────────────
    ark = Column(String(128))  # e.g. "ark:/99999/u1x7kq2m9b4cz" (unique index below)
    ark_assigned_at = Column(DateTime)

    # Which PID scheme is authoritative for this item: "ark" (we minted one) or
    # "handle" (harvested from our own IR, which already assigns a Handle).
    pid_source = Column(String(20))

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


class DepositBatch(Base):
    """Tracks a staged batch of items queued for deposit to the real DSpace IR.

    Flow: pending_approval → approved/rejected → depositing → completed/failed.
    An approval token is emailed to the address the admin typed in; only
    clicking the link in that email advances the batch to 'approved'.
    """

    __tablename__ = "deposit_batches"

    id = Column(Integer, primary_key=True)
    # Cryptographically random URL-safe token that authorises this specific batch.
    # Stored as-is (64 hex chars); treated as a one-time-use secret.
    token = Column(String(128), unique=True, index=True, nullable=False)

    # Lifecycle status
    status = Column(String(30), default="pending_approval", nullable=False, index=True)
    # Values: pending_approval | approved | rejected | depositing | completed | failed

    approval_email = Column(String(255), nullable=False)
    collection_uuid = Column(String(128))   # DSpace target collection UUID
    collection_name = Column(String(255))   # for display only

    # JSON array of local Item.id values to deposit, e.g. [1, 7, 42]
    item_ids_json = Column(Text, nullable=False, default="[]")
    item_count = Column(Integer, default=0)

    deposited_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)

    notes = Column(Text)           # rejection reason, or first fatal error
    requested_by = Column(String(100))  # session username

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)       # approval link expires after 48 h
    approved_at = Column(DateTime)
    completed_at = Column(DateTime)

    # JSON array of per-item results: [{"item_id": 1, "status": "ok", "dspace_id": "..."}, ...]
    deposit_log = Column(Text, default="[]")


# ── Indexes for query performance ─────────────────────────────────────────────
# ix_items_docid is auto-created by index=True on Item.docid — no duplicate needed
Index("ix_items_language", Item.language_code)
Index("ix_items_content_type", Item.content_type)
Index("ix_items_created_at", Item.created_at)
Index("ix_authors_orcid", Author.orcid)
Index("ix_authors_isni", Author.isni)
Index("ux_items_ark", Item.ark, unique=True)
Index("ux_communities_pmd", Community.pmd, unique=True)
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
    Base.metadata.create_all(bind=engine, checkfirst=True)


def sync_schema_columns():
    """Add any column declared on an ORM model but missing from the actual
    database table.

    create_all() only creates whole tables that don't exist yet — it never
    alters an existing table, so a database that predates some column
    (e.g. a persistent volume surviving across deploys) is silently left on
    its old schema forever, and the first query touching that column
    crashes. Confirmed live 2026-07-19: an HF Space failed to start
    entirely because its persistent DB predated Community.unit_type, and a
    synthetic even-older test schema also turned up a second, completely
    undocumented gap (Community.ror) with no dedicated migration script at
    all — one-column-at-a-time migration scripts don't scale to catching
    every possible drift. This is generic instead: it walks every declared
    ORM column and ALTERs in whatever the live table is missing, so it
    self-heals regardless of which columns happen to be absent or when they
    were added to the models.
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    added = 0
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # brand new table — create_all() already made it correctly
            existing_cols = {c["name"] for c in insp.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                try:
                    ddl_type = column.type.compile(dialect=engine.dialect)
                except Exception as e:
                    print(f"  [WARN] cannot compile DDL type for {table.name}.{column.name}: {e}")
                    continue
                stmt = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {ddl_type}"
                try:
                    conn.execute(text(stmt))
                    print(f"  -> {stmt}")
                    added += 1
                except Exception as e:
                    print(f"  [WARN] {stmt} failed: {e}")
    print(f"  schema sync: {added} missing column(s) added" if added else "  schema sync: already in sync")
