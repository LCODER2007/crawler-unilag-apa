# Define your item pipelines here
import json
import logging
import re
from datetime import date

from scrapy.exceptions import DropItem

from sqlalchemy import func

from uraas.config import config
from uraas.database import Author, Collection, Community, File, Item, SessionLocal
from uraas.services.sc_engine import category_breakdown, is_special_collection
from uraas.utils.ai_classifier import extract_keywords, sanitize_text
from uraas.utils.analytics_cache import analytics_cache
from uraas.utils.ark_generator import ark_generator
from uraas.utils.pdf_downloader import pdf_downloader
from uraas.utils.unilag_classifier import classifier

_ir_log = logging.getLogger("uraas.ir_deposit")

_DOI_RE = re.compile(r"^10\.\d{4,}/")


def _validate_doi(doi: str) -> bool:
    """Returns True if the DOI has a valid format."""
    if not doi:
        return False
    # Clean common prefixes
    doi = doi.replace("https://doi.org/", "").replace("http://dx.doi.org/", "").strip()
    return bool(_DOI_RE.match(doi))


class DatabaseStoragePipeline:
    def open_spider(self, spider):
        self.session = SessionLocal()
        self._cache_invalidated = False

        # Initialise DSpace client for auto-deposit if credentials are set.
        self._ir_client = None
        self._ir_collection_uuid = (config.DSPACE_COLLECTION_UUID or "").strip()
        if config.DISABLE_IR_DEPOSIT:
            _ir_log.info(
                "IR auto-deposit disabled via URAAS_DISABLE_IR_DEPOSIT (test/dry-run mode)"
            )
        elif config.DSPACE_USERNAME and config.DSPACE_PASSWORD:
            try:
                from uraas.services.ir_client import DSpaceClient, IRConnectionError
                self._ir_client = DSpaceClient()
                self._ir_client.login()
                # If no collection UUID is configured, use the first submittable one.
                if not self._ir_collection_uuid:
                    cols = self._ir_client.get_submittable_collections()
                    if cols:
                        self._ir_collection_uuid = cols[0]["uuid"]
                        _ir_log.info(
                            "IR auto-deposit: no DSPACE_COLLECTION_UUID set, "
                            "defaulting to first submittable collection: %s (%s)",
                            self._ir_collection_uuid, cols[0]["name"],
                        )
                    else:
                        _ir_log.warning(
                            "IR auto-deposit disabled: no submittable collections found. "
                            "Set DSPACE_COLLECTION_UUID in .env."
                        )
                        self._ir_client = None
                if self._ir_client:
                    _ir_log.info("IR auto-deposit enabled → collection %s", self._ir_collection_uuid)
            except Exception as exc:
                _ir_log.warning("IR auto-deposit disabled (login failed): %s", exc)
                self._ir_client = None

    def _enrich_existing_item(self, existing, item, spider):
        """A fresh crawl re-found a paper already in the DB (matched by DOI,
        URL, or title). Rather than discarding the new data, backfill any
        field the existing record is still missing — sources are often
        partial (e.g. an OAI-harvested stub has no abstract/DOI; a later
        OpenAlex/Crossref hit for the same paper carries the abstract, an
        openalex_id, citation counts, or ORCID-tagged authors the stub never
        had). This is also what feeds DOCID registration: title/abstract/
        creators/identifiers only get more complete over repeat crawls if
        we actually merge instead of skip.

        Conservative by design: only fills fields that are currently empty
        on the existing row (except cited_by_count, where we keep the max —
        a live re-crawl should never make a citation count go backwards).
        Never touches identity fields (title/doi/url) that drove the dedup
        match in the first place.
        """
        changed = False

        def _fill(attr, value):
            nonlocal changed
            if value not in (None, "", []) and not getattr(existing, attr):
                setattr(existing, attr, value)
                changed = True

        _fill("abstract", item.get("abstract"))
        _fill("pdf_url", item.get("pdf_url"))
        _fill("dc_subject", item.get("dc_subject"))
        _fill("openalex_id", item.get("openalex_id"))
        _fill("sdg_tags", item.get("sdg_tags"))
        _fill("language_code", item.get("language_code"))
        if item.get("is_african_language") and not existing.is_african_language:
            existing.is_african_language = True
            changed = True

        new_doi = item.get("doi")
        if new_doi and _validate_doi(new_doi) and not existing.doi:
            existing.doi = new_doi.replace("https://doi.org/", "").replace(
                "http://dx.doi.org/", ""
            ).strip()
            existing.dc_identifier_doi = existing.doi
            changed = True

        new_cited = int(item.get("cited_by_count") or 0)
        if new_cited > (existing.cited_by_count or 0):
            existing.cited_by_count = new_cited
            changed = True
        if item.get("counts_by_year") and not existing.counts_by_year:
            existing.counts_by_year = json.dumps(item["counts_by_year"])
            changed = True
        if item.get("funders") and not existing.funders:
            existing.funders = json.dumps(item["funders"])
            changed = True

        # Merge authors: add anyone not already linked, and backfill
        # orcid/ror on existing author links that were previously bare names.
        authors_full = item.get("authors_full") or [
            {"name": a, "orcid": "", "ror": ""} for a in item.get("authors", [])
        ]
        existing_names = {
            (a.normalized_name or "").strip() for a in existing.authors
        }
        for auth in authors_full:
            author_name = (auth.get("name") or "").strip()
            if not author_name:
                continue
            norm = author_name.lower()
            author_obj = (
                self.session.query(Author).filter_by(normalized_name=norm).first()
            )
            if not author_obj:
                author_obj = Author(
                    name=author_name,
                    normalized_name=norm,
                    orcid=auth.get("orcid", ""),
                    ror=auth.get("ror", ""),
                )
                self.session.add(author_obj)
            else:
                if auth.get("orcid") and not author_obj.orcid:
                    author_obj.orcid = auth["orcid"]
                    changed = True
                if auth.get("ror") and not author_obj.ror:
                    author_obj.ror = auth["ror"]
                    changed = True
            if norm not in existing_names:
                existing.authors.append(author_obj)
                existing_names.add(norm)
                changed = True

        if changed:
            try:
                self.session.commit()
                self._cache_invalidated = True
                spider.logger.info(
                    f"Enriched existing item id={existing.id}: {(existing.title or '')[:60]}"
                )
            except Exception as e:
                self.session.rollback()
                spider.logger.warning(f"Enrichment commit failed for id={existing.id}: {e}")

    def close_spider(self, spider):
        try:
            self.session.close()
        except Exception:
            pass
        # Invalidate analytics cache so fresh data shows immediately
        if self._cache_invalidated:
            analytics_cache.invalidate_all()

    def process_item(self, item, spider):
        try:
            # Validate item has required fields
            if not item.get("title"):
                spider.logger.error("Item missing title, skipping")
                return item

            # Sanitize title/abstract/subject BEFORE dedup/classification/storage —
            # several sources (Crossref, PubMed, Europe PMC, CORE, DataCite,
            # OpenAIRE) return raw JATS/HTML markup ("<jats:p>", "&amp;lt;i&amp;gt;")
            # embedded in these fields. Doing this once here (the single choke
            # point every spider's items pass through) fixes it for every
            # source instead of patching each spider individually.
            item["title"] = sanitize_text(item.get("title")) or item.get("title")
            if item.get("abstract"):
                item["abstract"] = sanitize_text(item["abstract"])
            if item.get("dc_subject"):
                item["dc_subject"] = sanitize_text(item["dc_subject"])

            if not item.get("title"):
                spider.logger.error("Item title became empty after sanitization, skipping")
                return item

            doi = item.get("doi") or None

            # Validate DOI format — reject malformed ones
            if doi and not _validate_doi(doi):
                spider.logger.warning(f"Malformed DOI rejected: {doi!r}")
                doi = None

            # Deduplicate by DOI first, then by URL, then by title
            if doi:
                doi = (
                    doi.replace("https://doi.org/", "")
                    .replace("http://dx.doi.org/", "")
                    .strip()
                )
                existing = self.session.query(Item).filter_by(doi=doi).first()
                if existing:
                    spider.logger.debug(f"Duplicate DOI skipped: {doi}")
                    self._enrich_existing_item(existing, item, spider)
                    return item

            url = item.get("url")
            if url:
                existing = self.session.query(Item).filter_by(url=url).first()
                if existing:
                    spider.logger.debug(f"Duplicate URL skipped: {url}")
                    self._enrich_existing_item(existing, item, spider)
                    return item

            # Deduplicate by normalised title (avoid same title from multiple sources).
            # Exact match on the full lowercased title (up to the column's max
            # length) — NOT a fuzzy match. A prior version used
            # Item.title.ilike(norm_title[:100]) with no wildcard characters,
            # which is actually a case-insensitive *equality* check truncated
            # to only the incoming title's first 100 chars, so it silently
            # never matched any stored title longer than that (i.e. most real
            # titles). func.lower() compares the full column value correctly.
            norm_title = (item.get("title") or "").strip().lower()
            if norm_title:
                existing = (
                    self.session.query(Item)
                    .filter(func.lower(Item.title) == norm_title[:512])
                    .first()
                )
                if existing:
                    spider.logger.debug(f"Duplicate title skipped: {norm_title[:60]}")
                    self._enrich_existing_item(existing, item, spider)
                    return item

            # Classify the document using enhanced classifier
            try:
                text_corpus = f"{item.get('title', '')} {item.get('abstract', '')} {item.get('raw_affiliation', '')}"
                classifications = classifier.classify(text_corpus, threshold=0.5)
            except Exception as e:
                spider.logger.error(f"Classification error: {e}")
                classifications = []

            provenance = f"Harvested via URAAS Crawler - {date.today().isoformat()}"

            # Extract AI keywords from title+abstract using the proper classifier
            try:
                ai_kws = extract_keywords(
                    item.get("title", ""), item.get("abstract", ""), top_n=20
                )
                tags = [k["word"] for k in ai_kws]
            except Exception as e:
                spider.logger.error(f"Keyword extraction error: {e}")
                tags = []

            # Determine institution from spider context
            institution_name = getattr(spider, "institution_name", None)
            institution_ror = getattr(spider, "ror_id", None)

            # Special Collections scoring — heavy weight on indigenous knowledge,
            # cultural heritage, African literature, etc. Score>0 marks the item as
            # part of a special collection; drives ranking on the dashboard.
            #
            # Uses uraas.services.sc_engine.is_special_collection — the guarded
            # 4-gate classifier (ambiguous-ethnonym guard, STEM/medical exclusion,
            # context corroboration), NOT uraas.utils.ai_classifier's unguarded
            # keyword-hit-count classifier, which every crawl used previously and
            # which accepts a paper on a single bare keyword hit with no
            # false-positive guarding at all.
            sc_score = 0.0
            sc_categories = ""
            sc_hits: list = []
            try:
                sc_subject = item.get("dc_subject", "") or ", ".join(tags[:15])
                is_sc, sc_score, categories = is_special_collection(
                    item.get("title", ""), item.get("abstract", ""), sc_subject
                )
                if is_sc:
                    sc_hits = category_breakdown(
                        item.get("title", ""), item.get("abstract", ""), sc_subject
                    )
                    sc_categories = ",".join(categories)
                    spider.logger.info(
                        f"SC HIT (score={sc_score:.1f}, cats={sc_categories}): "
                        f"{(item.get('title') or '')[:80]}"
                    )
            except Exception as e:
                spider.logger.error(f"Special-collections scoring error: {e}")

            # SC gate: only store papers classified as Special Collections
            if sc_score <= 0.0:
                raise DropItem(f"Not a special collection: {(item.get('title') or '')[:60]}")

            # Parse publication date — accept YYYY, YYYY-MM-DD, or full ISO timestamps.
            pub_date_raw = item.get("publication_date") or ""
            pub_date = None
            if pub_date_raw:
                try:
                    from datetime import datetime as _dt
                    pub_date_str = str(pub_date_raw).strip()
                    # BUG (found 2026-07-19, live-confirmed 0/54 items in
                    # production had publication_date set despite 40/54
                    # having a valid dc_date_issued string): this used to
                    # slice the input to len(fmt) before parsing — but fmt is
                    # the *format string* ("%Y-%m-%d" is 8 chars), not the
                    # expected *data* length ("2024-06-15" is 10 chars), so
                    # every real date got truncated mid-token and every
                    # strptime call failed silently, for every format, for
                    # every item, always. strptime doesn't need pre-slicing —
                    # it already fails cleanly on a non-matching string.
                    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m", "%Y"):
                        try:
                            pub_date = _dt.strptime(pub_date_str, fmt)
                            break
                        except ValueError:
                            continue
                except Exception:
                    pass

            # Normalise content/doc type
            raw_type = (item.get("content_type") or item.get("dc_type") or "").strip()
            # Map verbose DSpace dc:type values to our controlled vocabulary
            _type_map = {
                "thesis": "Thesis", "dissertation": "Thesis",
                "article": "Article", "journal article": "Article",
                "report": "Report", "technical report": "Report",
                "conference paper": "Article", "book chapter": "Article",
                "dataset": "Dataset", "preprint": "Article",
            }
            doc_type = _type_map.get(raw_type.lower(), raw_type) if raw_type else None

            # TK Vitality content_type — a *form* axis (paper/thesis/dataset/
            # patent), separate from dc_type's Dublin-Core display casing.
            # get_tk_vitality_score() (uraas/analytics/engine.py TK_WEIGHTS)
            # reads lowercase snake_case keys, which dc_type's Title-case
            # values never matched — every item silently fell through to the
            # generic 0.5 weight regardless of its real type. Prefer the SC
            # category (already computed above, sorted by score) for content
            # that IS indigenous knowledge / cultural heritage / oral
            # tradition; fall back to the normalised doc type; else a plain
            # research paper.
            _SC_CATEGORY_TO_CONTENT_TYPE = {
                "Indigenous Knowledge": "indigenous_knowledge",
                "Cultural Heritage": "cultural_heritage",
                "Ethnomusicology": "oral_tradition",
            }
            _DOCTYPE_TO_CONTENT_TYPE = {
                "Thesis": "thesis", "Dataset": "dataset",
                "Report": "grey_literature", "Article": "research_paper",
            }
            tk_content_type = None
            for hit in sc_hits:  # sc_hits sorted by -score; first match wins
                tk_content_type = _SC_CATEGORY_TO_CONTENT_TYPE.get(hit["category"])
                if tk_content_type:
                    break
            final_content_type = (
                tk_content_type
                or _DOCTYPE_TO_CONTENT_TYPE.get(doc_type, "research_paper")
            )

            # URL: fall back to None — never use a generic domain as unique URL
            item_url = item.get("url") or None

            # Create Item with Dublin Core metadata
            doc = Item(
                title=item.get("title"),
                dc_title=item.get("title"),
                dc_identifier_uri=doi or item_url,
                dc_identifier_doi=doi,
                dc_date_issued=pub_date_raw[:10] if pub_date_raw else None,
                dc_description_provenance=provenance,
                dc_rights=item.get(
                    "dc_rights", "info:eu-repo/semantics/restrictedAccess"
                ),
                dc_type=doc_type,
                dc_language=item.get("dc_language") or item.get("language_code") or None,
                abstract=item.get("abstract") or None,
                doi=doi,
                url=item_url,
                publication_date=pub_date,
                source_repository=item.get("source_repository"),
                pdf_url=item.get("pdf_url"),
                content_type=final_content_type,
                language_code=item.get("language_code") or item.get("dc_language") or None,
                is_african_language=bool(item.get("is_african_language", False)),
                # AI keywords (comma-separated)
                dc_subject=item.get("dc_subject") or ", ".join(tags[:15]),
                ai_keywords=", ".join(tags),
                sdg_tags=item.get("sdg_tags"),
                coauthor_countries=item.get("coauthor_countries") or None,
                african_country_count=int(item.get("african_country_count") or 0),
                is_intra_african=bool(item.get("is_intra_african", False)),
                openalex_id=item.get("openalex_id") or None,
                cited_by_count=int(item.get("cited_by_count") or 0),
                counts_by_year=(
                    json.dumps(item["counts_by_year"])
                    if item.get("counts_by_year")
                    else None
                ),
                funders=(
                    json.dumps(item["funders"]) if item.get("funders") else None
                ),
                # Institution tracking for multi-institution analytics
                institution=institution_name,
                ror=institution_ror,
                # Special Collections weighting
                special_collection_score=sc_score,
                special_collection_categories=sc_categories,
            )

            # Log to stdout for dashboard terminal
            try:
                safe_title = (
                    (item.get("title") or "")
                    .encode("ascii", errors="replace")
                    .decode("ascii")
                )
                print(f"URAAS_DOWNLOAD: {safe_title}", flush=True)
            except Exception:
                print(f"URAAS_DOWNLOAD: [Title encoding error]", flush=True)

            # Create Authors
            authors_full = item.get("authors_full", [])
            if not authors_full:
                # Fallback to simple list if authors_full is missing
                for a in item.get("authors", []):
                    authors_full.append({"name": a, "orcid": "", "ror": ""})

            for auth in authors_full:
                author_name = auth.get("name", "")
                try:
                    if not author_name or not isinstance(author_name, str):
                        continue
                    author_obj = (
                        self.session.query(Author)
                        .filter_by(normalized_name=author_name.lower().strip())
                        .first()
                    )

                    if not author_obj:
                        author_obj = Author(
                            name=author_name,
                            normalized_name=author_name.lower().strip(),
                            orcid=auth.get("orcid", ""),
                            ror=auth.get("ror", ""),
                        )
                        self.session.add(author_obj)
                    else:
                        # Update missing IDs if they are newly discovered
                        if auth.get("orcid") and not author_obj.orcid:
                            author_obj.orcid = auth["orcid"]
                        if auth.get("ror") and not author_obj.ror:
                            author_obj.ror = auth["ror"]

                    doc.authors.append(author_obj)
                except Exception as e:
                    spider.logger.error(f"Error processing author '{author_name}': {e}")
                    continue

            self.session.add(doc)
            self.session.flush()  # Get doc.id

            # PID assignment: items already carrying a repository-native Handle
            # (harvested from our own IR via OAI-PMH) use that Handle as the PID
            # of record rather than minting a redundant ARK.
            is_own_ir_record = bool(item.get("is_own_repository")) and bool(
                item.get("repository_handle")
            )
            if is_own_ir_record:
                doc.pid_source = "handle"
            else:
                try:
                    from datetime import datetime as _dt
                    ark_seed = doi or item_url or str(doc.id)
                    doc.ark = ark_generator.mint(ark_seed)
                    doc.ark_assigned_at = _dt.utcnow()
                    doc.pid_source = "ark"
                except Exception as e:
                    spider.logger.warning(f"ARK mint failed for item {doc.id}: {e}")

            # Map classified collections
            try:
                for community_name, collection_name, score in classifications[:3]:
                    try:
                        coll_obj = (
                            self.session.query(Collection)
                            .filter_by(name=collection_name)
                            .first()
                        )
                        if coll_obj and coll_obj not in doc.collections:
                            doc.collections.append(coll_obj)
                    except Exception as e:
                        spider.logger.error(
                            f"Error adding collection '{collection_name}': {e}"
                        )
                        continue
            except Exception as e:
                spider.logger.error(f"Error processing classifications: {e}")

            # Score framework alignment (AU charters, Agenda 2063, etc.)
            try:
                from uraas.services.alignment_engine import score_item_alignment
                al_json, al_ver = score_item_alignment(
                    doc.title or "", doc.abstract or "", doc.dc_subject or ""
                )
                doc.alignment_scores = al_json
                doc.alignment_version = al_ver
            except Exception as e:
                spider.logger.warning(f"Alignment scoring skipped for item: {e}")

            # Download PDF if available
            if doc.pdf_url:
                try:
                    policy = item.get("suggested_access", "Private")
                    # Cast explicitly to satisfy IDE static type checkers (MyPy)
                    pdf_metadata = pdf_downloader.download_pdf(str(doc.pdf_url), int(doc.id))  # type: ignore
                    if pdf_metadata:
                        bitstream = File(
                            item_id=doc.id,
                            file_path=pdf_metadata["file_path"],
                            sha256_hash=pdf_metadata["sha256_hash"],
                            access_policy=policy,
                        )
                        self.session.add(bitstream)
                except Exception as e:
                    spider.logger.error(f"PDF download error: {e}")

            self.session.commit()
            self._cache_invalidated = True

            # Auto-deposit into UNILAG IR if the client is configured.
            if self._ir_client is not None:
                try:
                    pdf_path = None
                    if doc.pdf_url:
                        # Resolve local file path from stored File record if present
                        f_rec = self.session.query(File).filter_by(item_id=doc.id).first()
                        if f_rec and f_rec.file_path:
                            import os as _os
                            if _os.path.exists(f_rec.file_path):
                                pdf_path = f_rec.file_path
                    result = self._ir_client.deposit_item(
                        self._ir_collection_uuid, doc, pdf_path=pdf_path
                    )
                    if result["status"] == "ok":
                        _ir_log.info(
                            "IR deposit OK → dspace_id=%s  title=%s",
                            result.get("dspace_id"), (doc.title or "")[:60],
                        )
                        print(
                            f"URAAS_IR_DEPOSIT: {(doc.title or '')[:80]}",
                            flush=True,
                        )
                    elif result["status"] == "duplicate":
                        _ir_log.debug("IR deposit skipped (duplicate): %s", (doc.title or "")[:60])
                    else:
                        _ir_log.warning("IR deposit failed: %s — %s", (doc.title or "")[:60], result.get("message"))
                except Exception as exc:
                    _ir_log.warning("IR deposit error for '%s': %s", (doc.title or "")[:60], exc)

            return item

        except DropItem:
            raise
        except Exception as e:
            spider.logger.error(
                f"Database storage error for '{item.get('title', 'Unknown')[:60]}': {e}"
            )
            try:
                self.session.rollback()
            except Exception:
                pass
            raise
