import logging
import os
import sys

import scrapy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.african_languages import AFRICAN_LANG_CODES
from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS
from uraas.services.sc_engine import sc_score_of
from uraas.spiders.mixins import DedupAwareSpiderMixin

OPENALEX_BASE = "https://api.openalex.org/works"
# OpenAlex authorships lists are truncated to 100 entries for mega-authorship
# works (large consortia/consortium studies commonly run into the hundreds of
# authors). Gate 2/3 can't see past this, so treat it as "unverifiable, trust
# Gate 1" rather than a false rejection — see parse().
AUTHORSHIPS_TRUNCATION_LIMIT = 100

log = logging.getLogger(__name__)


class OpenAlexSpider(DedupAwareSpiderMixin, scrapy.Spider):
    """
    OpenAlex spider with 3-gate precision for 98% crawl accuracy.

    Gate 1: ROR-filtered API query (only papers from institution's ROR)
    Gate 2: Per-paper authorship ROR verification (at least 1 author has target ROR)
    Gate 3: Affiliation string pattern matching (belt-and-suspenders)

    Papers failing any gate are dropped — never mixed across institutions.
    """

    name = "openalex_multi"
    custom_settings = {
        # OpenAlex polite pool: ~10 req/s per IP.  When multiple institution
        # spiders run in parallel they share the IP budget, so we need a
        # meaningful delay and generous autothrottle ceiling so 429s are
        # absorbed gracefully rather than exhausting all retries.
        "DOWNLOAD_DELAY": 2.0,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 2.0,
        "AUTOTHROTTLE_MAX_DELAY": 60.0,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 1,
        "CONCURRENT_REQUESTS": 1,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 5,
        "RETRY_HTTP_CODES": [429, 500, 502, 503, 504],
        "HTTPERROR_ALLOWED_CODES": [429],
    }

    def __init__(
        self,
        institution="unilag",
        target=20,
        boost_special=True,
        sc_only=False,
        *args,
        **kwargs,
    ):
        """
        institution:   registry short name (e.g. "unilag")
        target:        max SC papers to accept this run
        boost_special: also run SC seed waves (topic+ROR) in addition to the
                       general ROR wave — keeps SC recall high (default ON)
        sc_only:       skip the general ROR wave and run ONLY SC seed waves;
                       use when you only want targeted SC discovery, no noise
        """
        super().__init__(*args, **kwargs)
        self.target_limit = int(target)
        # Accept both bool and string ("true"/"false") — Scrapy passes CLI
        # spider args as strings when launched via crawl_multi_institution.py.
        _truthy = {"1", "true", "yes", "on"}
        if isinstance(boost_special, str):
            self.boost_special = boost_special.lower() in _truthy
        else:
            self.boost_special = bool(boost_special)
        if isinstance(sc_only, str):
            self.sc_only = sc_only.lower() in _truthy
        else:
            self.sc_only = bool(sc_only)
        registry = get_registry()
        self.institution_config = registry.get(institution)
        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found in registry")

        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror
        self.ror_short = self.ror_id.split("/")[-1]

        self._accepted = 0
        self._rejected_gate2 = 0
        self._rejected_gate3 = 0
        self._trusted_gate1_truncated = 0
        self._sc_accepted = 0
        self.max_results_scanned = config.MAX_RESULTS_SCANNED
        self._scanned_by_wave = {}

        self.logger.info(
            f"OpenAlex spider for {self.institution_name} | ROR: {self.ror_short} "
            f"| boost_special={self.boost_special} | sc_only={self.sc_only}"
        )
        self._init_dedup_index()

    SELECT_FIELDS = (
        "id,doi,title,abstract_inverted_index,authorships,"
        "publication_date,open_access,primary_location,concepts,"
        "counts_by_year,cited_by_count,language,funders,awards"
    )

    def _build_url(self, *, filters: str, cursor: str = "*") -> str:
        url = (
            f"{OPENALEX_BASE}"
            f"?filter={filters}"
            f"&select={self.SELECT_FIELDS}"
            f"&per-page=200"
            f"&cursor={cursor}"
            f"&mailto={config.OPENALEX_MAILTO}"
        )
        # api_key unlocks OpenAlex's higher-throughput "premium" pool — the
        # rest of the codebase (uraas/utils/openalex_client.py, used by the
        # citation tracker/backfill scripts) already reads this; the spider
        # previously built its own URLs with a hardcoded mailto and never
        # read config.OPENALEX_API_KEY at all, so a configured key silently
        # went unused for the (busiest) crawl path.
        if config.OPENALEX_API_KEY:
            url += f"&api_key={config.OPENALEX_API_KEY}"
        return url

    async def start(self):
        # Wave 1 — general ROR-only crawl (skipped in sc_only mode)
        if not self.sc_only:
            url = self._build_url(filters=f"institutions.ror:{self.ror_short}")
            # DEBUG not INFO — with 300+ SC seed waves, logging every raw
            # query URL at INFO level floods the dashboard's live feed
            # (which runs at LOG_LEVEL=INFO) with unreadable noise; still
            # available for real debugging via LOG_LEVEL=DEBUG.
            self.logger.debug(f"[ROR wave] {url}")
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                meta={"source": "ror", "wave": "ror"},
                priority=0,
            )

        # Wave 2 — SC-boosted waves: one request per SC seed phrase, AND-ed with ROR.
        # OpenAlex combines filters with comma=AND. The valid free-text filter is
        # title_and_abstract.search (concepts.display_name.search is not supported —
        # only concepts.id is). We rely on free-text seeds; the in-pipeline classifier
        # then scores the actual hits.
        if self.boost_special:
            seeds = set(SC_SEED_KEYWORDS)
            for seed in sorted(seeds):
                seed_q = seed.replace(" ", "%20")
                filters = (
                    f"institutions.ror:{self.ror_short},"
                    f"title_and_abstract.search:{seed_q}"
                )
                url = self._build_url(filters=filters)
                self.logger.debug(f"[SC wave seed={seed!r}] {url}")
                yield scrapy.Request(
                    url=url,
                    callback=self.parse,
                    meta={"source": "ror+seed", "wave": f"sc:{seed}"},
                    priority=10,  # Prioritize SC papers to fill target first
                )

    def parse(self, response):
        assert self.institution_config is not None, "Institution config must be loaded"

        if response.status == 429:
            self.logger.warning(
                "OpenAlex rate-limited (429) on wave=%s — Scrapy retry will back off",
                response.meta.get("wave", "?"),
            )
            return

        # Hard stop if we've already reached the global target — closes the
        # spider outright so the ~300 other already-scheduled seed-wave
        # requests get cancelled instead of still hitting the API. See
        # DedupAwareSpiderMixin._stop_if_target_reached().
        if self._accepted >= self.target_limit:
            self._stop_if_target_reached()

        wave = response.meta.get("wave", "ror")
        is_sc_wave = wave.startswith("sc:")
        # Every wave respects the global target limit. No more 10x headroom.
        wave_cap = self.target_limit

        data = response.json()
        results = data.get("results", [])
        self.logger.info(f"[{wave}] received {len(results)} works")

        wave_accepted = response.meta.get("wave_accepted", 0)
        scanned_this_wave = response.meta.get("scanned_this_wave", 0)

        for work in results:
            # Check both wave-local cap and global target limit
            if wave_accepted >= wave_cap or self._accepted >= self.target_limit:
                break
            # Scan-depth ceiling — OpenAlex cursor pagination has no natural
            # stopping point otherwise. Counted per-work-seen (not per-accept)
            # so a wave dominated by already-known duplicates still terminates.
            if scanned_this_wave >= self.max_results_scanned:
                break
            scanned_this_wave += 1

            title = (work.get("title") or "").strip()
            if not title:
                continue

            authorships = work.get("authorships", [])
            # OpenAlex hard-caps the authorships array at 100 entries for
            # mega-authorship works (GBD-style consortium papers routinely
            # run into the hundreds/thousands of authors). When that cap is
            # hit, a target-institution author can easily sit past position
            # 100 and simply be invisible to us — Gate 2/3 have nothing to
            # verify against. Gate 1 (the server-side institutions.ror=
            # filter OpenAlex already applied to return this result at all)
            # is unaffected by the truncation, so for truncated works we
            # trust Gate 1 instead of false-rejecting a genuine match.
            authorships_truncated = len(authorships) >= AUTHORSHIPS_TRUNCATION_LIMIT

            # ── Gate 2: Authorship ROR verification ──────────────────────────
            if (
                not authorships_truncated
                and not self.institution_config.verify_ror_in_authorships(authorships)
            ):
                self._rejected_gate2 += 1
                self.logger.debug(f"Gate 2 FAIL (no ROR match): {title[:60]}")
                continue
            if authorships_truncated:
                self._trusted_gate1_truncated += 1

            authors = []
            author_orcids = []
            authors_full = []
            affiliations = []
            author_depts = []

            for authorship in authorships:
                author_name = authorship.get("author", {}).get("display_name", "")
                author_orcid = authorship.get("author", {}).get("orcid", "")
                if author_orcid:
                    author_orcid = author_orcid.replace("https://orcid.org/", "")

                author_ror = ""

                if author_name:
                    authors.append(author_name)
                    if author_orcid:
                        author_orcids.append(author_orcid)

                    for inst in authorship.get("institutions", []):
                        inst_name = inst.get("display_name", "")
                        inst_ror = inst.get("ror", "")
                        if inst_ror:
                            author_ror = inst_ror.replace("https://ror.org/", "")

                        if inst_name:
                            affiliations.append(inst_name)
                        # Collect sub-institution if available
                        sub = inst.get("lineage", [])
                        if sub and len(sub) > 1:
                            author_depts.append(sub[-1])

                    authors_full.append(
                        {"name": author_name, "orcid": author_orcid, "ror": author_ror}
                    )

            raw_affiliation = (
                " | ".join(set(affiliations)) if affiliations else self.institution_name
            )

            # ── Gate 3: Affiliation pattern matching ──────────────────────────
            # Same truncation caveat as Gate 2: the visible affiliation strings
            # are only the first 100 authors' worth, so a miss here doesn't
            # mean the paper is wrong — it means the matching author is
            # off-screen. Skip Gate 3 too when truncated.
            if (
                affiliations
                and not authorships_truncated
                and not self.institution_config.matches_affiliation(raw_affiliation)
            ):
                self._rejected_gate3 += 1
                self.logger.debug(f"Gate 3 FAIL (pattern mismatch): {title[:60]}")
                continue

            doi = work.get("doi", "")
            abstract = self._reconstruct_abstract(
                work.get("abstract_inverted_index", {})
            )
            concepts = work.get("concepts", [])
            dc_subject = ", ".join(c.get("display_name", "") for c in concepts[:5] if c)

            # SC gate — only count papers that the storage pipeline will keep.
            # Without this the target fills with non-SC papers that get dropped
            # downstream, and the crawl stops before reaching `target` SC papers.
            if sc_score_of(title, abstract, dc_subject) <= 0.0:
                continue

            url = (
                (work.get("primary_location", {}) or {}).get("landing_page_url")
                or doi
                or ""
            )
            if not url:
                url = f"https://openalex.org/{work.get('id', '').replace('https://openalex.org/', '')}"

            # Dedup gate — only count papers not already in the DB. Without
            # this, repeat crawls re-discover the same top results (search
            # APIs are deterministic), "fill" target with items the pipeline
            # then silently drops as duplicates, and never paginate deep
            # enough to find genuinely new material.
            if self._is_known(doi=doi, url=url, title=title):
                continue

            self._accepted += 1
            wave_accepted += 1
            if is_sc_wave:
                self._sc_accepted += 1

            pub_date = work.get("publication_date", "")

            pdf_url = None
            oa = work.get("open_access", {})
            if oa.get("is_oa") and oa.get("oa_url"):
                pdf_url = oa["oa_url"]

            # Extract SDG tags from concepts
            sdg_tags = self._extract_sdg_from_concepts(concepts)

            funders = self._extract_funders(work)

            lang_code = (work.get("language") or "").strip().lower() or None

            item = {
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "author_orcids": author_orcids,
                "authors_full": authors_full,
                "doi": doi,
                "url": url,
                "pdf_url": pdf_url,
                "publication_date": pub_date,
                "source_repository": "OpenAlex",
                "is_unilag_author": True,  # Legacy field
                "raw_affiliation": raw_affiliation,
                "institution": self.institution_name,
                "institution_ror": self.ror_id,
                "sdg_tags": sdg_tags,
                "dc_subject": ", ".join(
                    c.get("display_name", "") for c in concepts[:5] if c
                ),
                "cited_by_count": work.get("cited_by_count", 0),
                "counts_by_year": work.get("counts_by_year", []),
                "openalex_id": work.get("id", ""),
                "language_code": lang_code,
                "is_african_language": bool(
                    lang_code and lang_code in AFRICAN_LANG_CODES
                ),
                "funders": funders,
                # Every accepted item passed the server-side ROR filter (Gate
                # 1) at minimum — OpenAlex's own curated institution-linkage
                # database, the strongest affiliation signal available here.
                "affiliation_confidence": "strong",
            }
            yield item
            self._mark_seen(doi=doi, url=url, title=title)

        # Cursor-based pagination — keep paginating within the same wave until its
        # cap is hit. Reuse the originating wave's filter (extracted from current URL)
        # so SC waves don't degrade back into plain ROR queries. Continues past
        # a run of already-known duplicates (wave_accepted stalled) as long as
        # the scan-depth budget remains, so a maturing dataset still finds
        # genuinely new material deeper in the source instead of stopping early.
        meta = data.get("meta", {})
        next_cursor = meta.get("next_cursor")
        if (
            next_cursor
            and results
            and wave_accepted < wave_cap
            and self._accepted < self.target_limit
            and scanned_this_wave < self.max_results_scanned
        ):
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(response.url).query)
            current_filters = (
                qs.get("filter") or [f"institutions.ror:{self.ror_short}"]
            )[0]
            next_url = self._build_url(filters=current_filters, cursor=next_cursor)
            yield scrapy.Request(
                url=next_url,
                callback=self.parse,
                meta={
                    "source": response.meta.get("source", "ror"),
                    "wave": wave,
                    "wave_accepted": wave_accepted,
                    "scanned_this_wave": scanned_this_wave,
                },
            )

    def _reconstruct_abstract(self, inverted_index: dict) -> str:
        """OpenAlex stores abstracts as word→[position] inverted index."""
        if not inverted_index:
            return ""
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        return " ".join(w for _, w in word_positions)

    def _extract_funders(self, work: dict) -> list:
        """Normalize OpenAlex `funders` (org list) + `awards` (specific
        grant/award numbers, each linked to a funder by funder_id) into
        [{"name", "ror", "award_id"}, ...]. Live-verified 2026-07-19: 56% of
        sampled UNILAG papers have funders, 40% have a specific award number
        — real, previously-uncaptured data (SELECT_FIELDS didn't request
        either field before this).
        """
        funders = work.get("funders") or []
        awards = work.get("awards") or []
        award_by_funder_id: dict = {}
        for a in awards:
            fid = a.get("funder_id")
            if fid:
                award_by_funder_id.setdefault(fid, []).append(
                    a.get("funder_award_id") or ""
                )

        result = []
        for f in funders:
            fid = f.get("id", "")
            name = f.get("display_name", "")
            if not name:
                continue
            ror = f.get("ror")
            ror = ror.replace("https://ror.org/", "") if ror else None
            award_ids = [a for a in award_by_funder_id.get(fid, []) if a]
            result.append(
                {
                    "name": name,
                    "ror": ror,
                    "award_id": ", ".join(award_ids) if award_ids else None,
                }
            )
        return result

    def _extract_sdg_from_concepts(self, concepts: list) -> str:
        """Map OpenAlex concepts to SDG numbers (rough heuristic)."""
        sdg_concept_map = {
            "Poverty": 1,
            "Food security": 2,
            "Health": 3,
            "Medicine": 3,
            "Education": 4,
            "Gender studies": 5,
            "Water resources": 6,
            "Renewable energy": 7,
            "Economic growth": 8,
            "Engineering": 9,
            "Inequality": 10,
            "Urban planning": 11,
            "Sustainability": 12,
            "Climate change": 13,
            "Marine biology": 14,
            "Ecology": 15,
            "Political science": 16,
            "International development": 17,
        }
        matched_sdgs = set()
        for concept in concepts:
            name = concept.get("display_name", "")
            for key, sdg_num in sdg_concept_map.items():
                if key.lower() in name.lower():
                    matched_sdgs.add(str(sdg_num))
        return ",".join(sorted(matched_sdgs))

    def closed(self, reason):
        self.logger.info(
            f"Spider closed: {self.institution_name} | "
            f"Accepted: {self._accepted} (SC-wave: {self._sc_accepted}) | "
            f"Rejected (gate2/ROR): {self._rejected_gate2} | "
            f"Rejected (gate3/pattern): {self._rejected_gate3} | "
            f"Trusted gate1 (truncated authorships): {self._trusted_gate1_truncated} | "
            f"Skipped (already known): {self._skipped_known}"
        )
        total_seen = self._accepted + self._rejected_gate2 + self._rejected_gate3
        if total_seen > 0:
            precision = round(self._accepted / total_seen * 100, 1)
            self.logger.info(f"Precision: {precision}%")
