# Crawling Problems Encountered & Fixes

## Overview

This report documents the problems encountered while crawling academic sources
(OpenAlex, Crossref, arXiv, AJOL, DOAJ, OAI-PMH/DSpace, OpenAIRE, Semantic
Scholar) and the fixes applied in this codebase. Findings were gathered by
(1) reading the current spider/pipeline code for error handling, workarounds,
and explanatory comments, and (2) mining git history for the commits that
introduced fixes. Every item below is grounded in a `file:line` reference or a
commit hash so it can be re-verified against the repo.

---

## 1. Per-Source Problems

### OpenAlex (`uraas/spiders/sources/openalex_spider.py`)

| Problem | Fix |
|---|---|
| OpenAlex's polite pool allows ~10 req/s **per IP**, shared across all institution spiders running in parallel — this caused 429 (rate limit) responses. | Raised `DOWNLOAD_DELAY` to 2.0s, `CONCURRENT_REQUESTS` to 1, `AUTOTHROTTLE_MAX_DELAY` to 60s, `RETRY_TIMES` to 5 on `[429,500,502,503,504]`, and allowed 429 through as a handled (not fatal) status so it's logged and backed off gracefully instead of exhausting retries (`openalex_spider.py:31-46`). |
| `concepts.display_name.search` is not a valid OpenAlex filter (only `concepts.id` is supported). | Free-text concept search uses `title_and_abstract.search` instead (`openalex_spider.py:128-129`). |
| OpenAlex returns abstracts as a word→position **inverted index**, not plain text. | `_reconstruct_abstract()` rebuilds the string by sorting tokens back into position order (`openalex_spider.py:325-334`). |
| Papers from different institutions were getting mixed together when only relying on the API's institution filter. | Added a 3-gate precision design: (1) ROR-filtered query, (2) per-author ROR verification, (3) affiliation-string pattern matching as a belt-and-suspenders check — papers failing any gate are dropped (`openalex_spider.py:19-27`, gates at `184-187`, `230-235`). |
| Spiders counted every API result toward their crawl `target`, but the storage pipeline later silently dropped non-Special-Collections (SC) papers — crawls halted early having "hit target" with mostly-discarded items. | Added `sc_score_of()`, mirroring the pipeline's own SC gate, and call it **inside the spider** before counting an item toward target (`openalex_spider.py:244-248`; gate added in commit `f6038f1`). An earlier inline gate (`is_special_collection()`) was tried and later removed as redundant/inconsistent with other spiders (commit `94a4707`). |
| OpenAlex announced deprecation of keyless (anonymous) access. | Added `OPENALEX_API_KEY` configuration for production use (`config/__init__.py:88-90`). |
| Citations always showed 0 downstream. | Root cause: the spider never requested `counts_by_year`/`cited_by_count` fields from the API. Fixed by requesting those fields and persisting them (see §3 Citation Pipeline, commit `7dd86da`). |

### Crossref (`uraas/spiders/sources/crossref_spider.py`)

| Problem | Fix |
|---|---|
| Anonymous/non-descriptive requests are throttled harder by Crossref. | Sets a descriptive `USER_AGENT` with a `mailto` contact to qualify for Crossref's "polite pool" (`crossref_spider.py:19-24`). |
| **False positives**: the spider originally accepted any result matching the institution query string, without checking whether an author was actually affiliated with the institution. | Added real affiliation verification — parses `author[].affiliation[].name` and rejects items where none match `matches_affiliation()`, tracking rejections via a `_rejected_aff` counter logged at spider close (commit `94a4707`). Because Crossref's affiliation field is often empty, items with *no* affiliation data are still accepted rather than rejected, relying on the query-level filter instead (`crossref_spider.py:124-126,139-144`). |
| Unbounded pagination risk. | Hard cap at `offset < 500` (`crossref_spider.py:173-179`). |

### arXiv (`uraas/spiders/sources/arxiv_spider.py`)

| Problem | Fix |
|---|---|
| The `arxiv.org/search` HTML page is fragile and layout-dependent, breaking scraping when arXiv changed its page structure. | Rewritten to use the stable Atom API instead of HTML scraping (`arxiv_spider.py:3-9`). |
| arXiv recommends no more than 1 request per 3 seconds. | `DOWNLOAD_DELAY=1.5`, `CONCURRENT_REQUESTS=1` (`arxiv_spider.py:9,43-44`). |
| Malformed/unparseable Atom XML crashed the spider. | Wrapped parsing in `try/except ElementTree.ParseError`, logging and skipping the response (`arxiv_spider.py:118-122`). |
| Paginated/fan-out queries returned duplicate entries. | `_seen_ids` set dedupes by arXiv ID (`arxiv_spider.py:77,130-132`). |
| arXiv is overwhelmingly CS/STEM, so the full Special-Collections keyword seed list produced irrelevant fan-out queries. | Uses a curated `_SC_RELEVANT` keyword subset instead of the full SC list (`arxiv_spider.py:33-37,96-102`). |

### AJOL (`uraas/spiders/sources/ajol_spider.py`)

| Problem | Fix |
|---|---|
| AJOL returns HTTP 403 to non-browser user agents. | Spoofs a real Chrome `USER_AGENT` and full browser-like headers, and allows 403/429 through Scrapy so they're logged and skipped rather than crashing (`ajol_spider.py:47-59,129-131,178-180`). |
| The legacy OJS search path (`index.php/ajol/search/results`) started returning 404 after AJOL's platform upgrade. | Switched to `https://www.ajol.info/search/search` (`ajol_spider.py:31-32`). |
| AJOL's HTML structure is unstable/inconsistent across pages. | Multiple CSS-selector fallback chains for result items, titles, abstracts, authors, DOI, PDF link, and publication date (`ajol_spider.py:137-140,181-218`). |
| DOI and affiliation data are often missing or unstructured. | DOI extracted via regex fallback from arbitrary link text; affiliation matching falls back to scanning the full page text if a dedicated selector fails (`ajol_spider.py:33,202-206,226-231`). |
| No reliable "next page" link. | Falls back to manual numeric pagination up to page 5 when `rel=next`/`.next` selectors are absent (`ajol_spider.py:169-174`). |

### DOAJ (`uraas/spiders/sources/doaj_spider.py`)

| Problem | Fix |
|---|---|
| DOAJ's v3 API returns HTTP 400 on compound `field:value` queries (e.g. combining institution + keyword). | Avoids `field:value` syntax entirely — uses plain free-text query segments and does affiliation filtering post-hoc in `parse()` instead (`doaj_spider.py:66-68,90-93,122-127`). |
| Occasional malformed JSON responses. | Wrapped `response.json()` in `try/except`, logging and returning instead of raising (`doaj_spider.py:104-108`). |

### OAI-PMH / DSpace (`uraas/spiders/sources/oai_spider.py`)

| Problem | Fix |
|---|---|
| Some DSpace servers — **including UNILAG's own repository** — return HTTP 500 on the `ListRecords` verb, while `ListIdentifiers` and `GetRecord` work correctly. | The entire spider is architected around `ListIdentifiers` (paginated via resumption token) + a per-record `GetRecord` call, instead of the more efficient but broken `ListRecords` (`oai_spider.py:1-9,36-42`). |
| Large default harvest date-ranges also triggered 500s on DSpace (servers struggle with very large ranges). | Widened the default lookback window to ~5 years (`_DEFAULT_LOOKBACK_DAYS = 1825`) and added an `oai_set` parameter to scope harvests to a specific DSpace community/collection, cutting request volume (`oai_spider.py:33`; commit `94a4707`). |
| 500 responses on individual `GetRecord` calls are common/expected for stale identifiers and would otherwise crash the spider. | `HTTPERROR_ALLOWED_CODES: [500]` allows them through; listing-call 500s are logged at error level, individual record 500s at debug level since they're expected noise (`oai_spider.py:59,146-148,183-185`). |
| OAI protocol-level error responses (e.g. `badResumptionToken`). | Checks `//oai:error/@code` and logs a warning rather than crashing (`oai_spider.py:154-157`). |
| Inconsistent identifier schemes inside `dc:identifier` (mix of DOI, handle URL, other links). | `_pick_url_and_doi()` heuristically scans all values, extracting a DOI (`doi.org/` or `10.` prefix) and preferring `/handle/` URLs for the landing page (`oai_spider.py:244-256`). |
| Inconsistent date formats (date-only vs. timestamped). | `_pick_publication_date()` prefers date-only strings, excluding any containing `"T"` (`oai_spider.py:258-263`). |
| Ambiguous free-text rights metadata. | `_map_rights()` heuristically maps `dc:rights` text to an open/restricted binary via substring matching against known open-access markers (`oai_spider.py:265-271`). |

### OpenAIRE (`uraas/spiders/sources/openaire_spider.py`)

| Problem | Fix |
|---|---|
| The older `search/publications` (v2) endpoint returns HTTP 400 for combined keyword+affiliation queries. | Migrated to the Graph API v1 (`researchProducts`) endpoint instead (`openaire_spider.py:28-29`). |
| Inconsistent field typing across records — `description` can be a string or a list; title appears under either `title` or `mainTitle`; `results` is sometimes not a list. | Defensive `isinstance` branching to normalize `description`; fallback chain for title key; `results` coerced to `[]` if not already a list (`openaire_spider.py:83-85,91,95-96`). |
| Inconsistent publication-date fields. | Falls back from `publicationYear` to `publicationDate` (truncated to 4 chars) (`openaire_spider.py:112`). |

### Semantic Scholar (`uraas/spiders/sources/semantic_scholar_spider.py`)

| Problem | Fix |
|---|---|
| Aggressive rate limiting causing frequent 429s. | Doubled `DOWNLOAD_DELAY` (3→6s), doubled `AUTOTHROTTLE_MAX_DELAY` (30→120s), raised `RETRY_TIMES` (3→5), added `RETRY_BACKOFF_BASE/MAX` (commit `f6038f1`). |
| `fieldsOfStudy` items were assumed to always be dicts (`f.get("category")`), but the API sometimes returns raw strings — this crashed the spider. | Now handles both string and dict entries (commit `f6038f1`). |

---

## 2. Cross-Cutting Engine / Infrastructure Issues

| Problem | Fix |
|---|---|
| A newer Scrapy release broke the legacy `start_requests()` API that every spider relied on. | Pinned `scrapy<2.15.0` (commit `3c4e230`) and migrated **all** source spiders (AJOL, arXiv, CORE, Crossref, DOAJ, Europe PMC, OAI, OpenAIRE, OpenAlex, PubMed, Semantic Scholar) from `start_requests()` to `async def start()` to align with the compatible/newer API shape (commit `94a4707`). |
| Scrapy's telnet debug console caused "conch negotiation" errors under gevent workers. | Disabled `TELNETCONSOLE_ENABLED` (commit `01b21fe`). |
| Scrapy deprecated the `spider` argument on `open_spider`/`close_spider` pipeline hooks. | Removed the deprecated argument from `affiliation_filter.py`, `database.py`, and `gap_analysis.py`; replaced eager per-spider init with lazy `_ensure_institution()` calls inside `process_item` (commit `2f30e80`). |

---

## 3. Pipeline / Data-Quality Issues (`uraas/pipelines/database.py`)

| Problem | Fix |
|---|---|
| The same paper is frequently returned by multiple sources (e.g. OpenAlex + Crossref + DOAJ), causing duplicate ingestion. | Three-tier deduplication: normalized DOI match (`database.py:93-103`), URL match (`105-110`), then normalized/truncated title `ILIKE` match (`112-122`). |
| Malformed DOIs (with or without URL prefixes) polluting the database. | `_validate_doi()` strips `https://doi.org/`/`http://dx.doi.org/` prefixes and validates against `^10\.\d{4,}/`, rejecting (setting `None`) anything malformed with a warning log (`database.py:23-32,86-91`). |
| A single bad record (failed classification, keyword extraction, alignment scoring, author/collection mapping, PDF download, or IR deposit) could abort ingestion of an entire crawl batch. | Each stage is wrapped in its own `try/except`, logging and degrading gracefully (empty list/0 score/skip) rather than raising (`database.py:125-130,135-142,153-167,266-295,309-326,329-337,340-354,360-387`). |
| Publication dates arrive in at least 5 different formats across sources (`YYYY`, `YYYY-MM`, `YYYY-MM-DD`, two ISO-timestamp variants). | Tries all 5 `strptime` formats in sequence (`database.py:174-187`). |
| Document-type vocabulary varies by source (e.g. verbose DSpace `dc:type` strings like "technical report", "conference paper"). | `_type_map` normalizes these into a controlled vocabulary (`database.py:189-199`). |
| Non-ASCII titles broke console/stdout logging. | Titles are encoded `ascii, errors="replace"` before printing, with a fallback print on any encoding exception (`database.py:249-257`). |
| IR (DSpace) login failure at pipeline startup used to fail the whole spider run. | Login failures are caught at pipeline-open time; auto-deposit is disabled for that run instead of crashing startup (`database.py:44-68`). |

---

## 4. Special Collections (AI Classifier) Target-Gating Bug

Spiders were counting items toward their crawl `target` before the storage
pipeline's Special-Collections (SC) relevance gate ran. This meant a crawl
could report "target reached" while the pipeline silently discarded most of
those items as not SC-relevant, so real output under-delivered (this affected
Semantic Scholar and other spiders in addition to OpenAlex).

**Fix:** Added `sc_score_of()` to `uraas/utils/ai_classifier.py`, mirroring
the pipeline's own gate logic, and call it directly inside each spider so
only genuinely SC-accepted items count toward the target (commit `f6038f1`).

---

## 5. Citation Data Pipeline

Citation counts and metrics displayed as 0/empty for an extended period.
Three separate root causes were found and fixed:

1. The OpenAlex spider never requested the `counts_by_year`/`cited_by_count`
   fields from the API in the first place.
2. Even when present, the database pipeline never persisted `counts_by_year`
   onto the stored item.
3. `african_citation_share` was never computed automatically.

**Fix:** Request and persist the missing fields, and add a background
`_auto_backfill_citation_share()` thread that runs after every crawl
(commit `7dd86da`).

Additional related fixes:
- `backfill_citation_velocity.py` called `CitationTracker.fetch_work_velocity`
  / `fetch_african_citation_share`, but those methods didn't exist yet,
  crashing the script; and `citation_tracker` was never imported in
  `scripts/init_db.py`, so SQLAlchemy never registered the `citations`,
  `citation_metrics`, and `author_metrics` tables — they were silently
  absent on fresh databases (commit `7a7dbb2`).
- The dashboard's `get_citations` logic let a live `CitationMetrics` lookup
  overwrite the authoritative crawl-time `cited_by_count` down to 0; fixed to
  retain the highest trustworthy count and only lazily fetch live data from
  OpenAlex/Crossref when a DOI exists but no count is yet stored
  (commit `f6038f1`).

---

## 6. IR (Institutional Repository) Deposit Workflow

**Problem:** An SMTP email-approval gate blocked automatic deposit of
harvested items into the DSpace institutional repository — deposits sat
waiting on a manual email step that wasn't reliably actioned.

**Fix:** Removed the SMTP gate; `queue_batch` now auto-approves and deposits
directly to the live DSpace IR using crawler credentials, retaining the
`DepositBatch` database row for audit purposes only (commit `f6038f1`).

---

## 7. Downstream Effects on Dashboard/Analytics

Several dashboard bugs were direct downstream consequences of upstream
crawl/data-quality issues, included here to show the full impact chain:

- Open Science Health Score rendered as `[object Object]%` (frontend read the
  wrong nested field from the analytics response).
- KRI classification defaulted every record to "Unclassified" when
  `coauthor_countries` was `NULL` — added an Africa-led fallback.
- Charter Alignment scores were always zero because the scoring function had
  never been wired into the ingest pipeline.
- The CARTO tile server the map relied on stopped loading (blank canvas) and
  risked CSP issues; replaced with a self-contained dark MapLibre style
  requiring zero external tile requests (commit `dc5c20d`).

(All from commit `94a4707` unless noted otherwise.)

---

## 8. Summary Table

| Source/Area | Problem Category | Fix Status |
|---|---|---|
| OpenAlex | Rate limiting, invalid filter, abstract format, cross-institution contamination, target gating, key deprecation | Resolved |
| Crossref | Affiliation false positives, sparse data, pagination | Resolved |
| arXiv | Fragile HTML source, malformed XML, duplicates, domain mismatch | Resolved |
| AJOL | 403 blocking, broken URL path, unstable HTML, weak metadata | Resolved |
| DOAJ | Compound-query 400s, malformed JSON | Resolved |
| OAI-PMH/DSpace | `ListRecords` 500s, large date-range 500s, inconsistent metadata | Resolved |
| OpenAIRE | Deprecated endpoint, inconsistent field typing | Resolved |
| Semantic Scholar | Rate limiting, type-inconsistent fields | Resolved |
| Engine/infra | Scrapy version drift, telnet console errors, deprecated pipeline hooks | Resolved |
| Pipeline | Duplicate ingestion, malformed DOIs, cascading failures, date/type vocabulary drift | Resolved |
| SC Classifier | Target-gating under-delivery | Resolved |
| Citations | Missing fields, missing tables, live-data clobbering | Resolved |
| IR Deposit | SMTP approval bottleneck | Resolved |
| Dashboard | Downstream rendering/classification bugs from upstream data gaps | Resolved |

---

*Compiled from source-code inspection (spiders, pipelines, config) and git
history as of commit `f6038f1`.*
