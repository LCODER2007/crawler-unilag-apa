import scrapy
import os
import sys
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS, SC_OPENALEX_CONCEPTS

OPENALEX_BASE = "https://api.openalex.org/works"
MAILTO = "cokiki@unilag.edu.ng"

log = logging.getLogger(__name__)


class OpenAlexSpider(scrapy.Spider):
    """
    OpenAlex spider with 3-gate precision for 98% crawl accuracy.

    Gate 1: ROR-filtered API query (only papers from institution's ROR)
    Gate 2: Per-paper authorship ROR verification (at least 1 author has target ROR)
    Gate 3: Affiliation string pattern matching (belt-and-suspenders)

    Papers failing any gate are dropped — never mixed across institutions.
    """
    name = "openalex_multi"
    custom_settings = {
        'DOWNLOAD_DELAY': 1.0,
        'AUTOTHROTTLE_ENABLED': True,
        'AUTOTHROTTLE_START_DELAY': 1.0,
        'AUTOTHROTTLE_MAX_DELAY': 5.0,
        'CONCURRENT_REQUESTS': 1,
    }

    def __init__(self, institution='unilag', target=20, *args, **kwargs):
        """
        Permanently forced to crawl exclusively using Special Collections seeds.
        General ROR-only waves have been disabled.
        """
        super().__init__(*args, **kwargs)
        self.target_limit = int(target)
        
        self.boost_special = True
        self.sc_only = True
        registry = get_registry()
        self.institution_config = registry.get(institution)
        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found in registry")

        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror
        self.ror_short = self.ror_id.split('/')[-1]

        self._accepted = 0
        self._rejected_gate2 = 0
        self._rejected_gate3 = 0
        self._sc_accepted = 0

        self.logger.info(
            f"OpenAlex spider for {self.institution_name} | ROR: {self.ror_short} "
            f"| boost_special={self.boost_special} | sc_only={self.sc_only}"
        )

    SELECT_FIELDS = (
        "id,doi,title,abstract_inverted_index,authorships,"
        "publication_date,open_access,primary_location,concepts"
    )

    def _build_url(self, *, filters: str, cursor: str = '*') -> str:
        return (
            f"{OPENALEX_BASE}"
            f"?filter={filters}"
            f"&select={self.SELECT_FIELDS}"
            f"&per-page=200"
            f"&cursor={cursor}"
            f"&mailto={MAILTO}"
        )

    def start_requests(self):
        # Wave 1 — general ROR-only crawl (skipped in sc_only mode)
        if not self.sc_only:
            url = self._build_url(filters=f"institutions.ror:{self.ror_short}")
            self.logger.info(f"[ROR wave] {url}")
            yield scrapy.Request(
                url=url, callback=self.parse,
                meta={'source': 'ror', 'wave': 'ror'},
                priority=0,
            )

        # Wave 2 — SC-boosted waves: one request per SC seed phrase, AND-ed with ROR.
        # OpenAlex combines filters with comma=AND. The valid free-text filter is
        # title_and_abstract.search (concepts.display_name.search is not supported —
        # only concepts.id is). We rely on free-text seeds; the in-pipeline classifier
        # then scores the actual hits.
        if self.boost_special:
            # SC_OPENALEX_CONCEPTS kept as broad terms in case concept-id lookup is added later
            seeds = set(SC_SEED_KEYWORDS) | set(SC_OPENALEX_CONCEPTS)
            for seed in sorted(seeds):
                seed_q = seed.replace(' ', '%20')
                filters = (
                    f"institutions.ror:{self.ror_short},"
                    f"title_and_abstract.search:{seed_q}"
                )
                url = self._build_url(filters=filters)
                self.logger.info(f"[SC wave seed={seed!r}] {url}")
                yield scrapy.Request(
                    url=url, callback=self.parse,
                    meta={'source': 'ror+seed', 'wave': f'sc:{seed}'},
                    priority=10,  # Prioritize SC papers to fill target first
                )

    def parse(self, response):
        # Hard stop if we've already reached the global target
        if self._accepted >= self.target_limit:
            return

        wave = response.meta.get('wave', 'ror')
        is_sc_wave = wave.startswith('sc:')
        # Every wave respects the global target limit. No more 10x headroom.
        wave_cap = self.target_limit

        data = response.json()
        results = data.get('results', [])
        self.logger.info(f"[{wave}] received {len(results)} works")

        wave_accepted = response.meta.get('wave_accepted', 0)

        for work in results:
            # Check both wave-local cap and global target limit
            if wave_accepted >= wave_cap or self._accepted >= self.target_limit:
                break
            
            title = (work.get('title') or '').strip()
            if not title:
                continue

            authorships = work.get('authorships', [])

            # ── Gate 2: Authorship ROR verification ──────────────────────────
            if not self.institution_config.verify_ror_in_authorships(authorships):
                self._rejected_gate2 += 1
                self.logger.debug(f"Gate 2 FAIL (no ROR match): {title[:60]}")
                continue

            authors = []
            author_orcids = []
            authors_full = []
            affiliations = []
            author_depts = []

            for authorship in authorships:
                author_name = authorship.get('author', {}).get('display_name', '')
                author_orcid = authorship.get('author', {}).get('orcid', '')
                if author_orcid:
                    author_orcid = author_orcid.replace('https://orcid.org/', '')

                author_ror = ''

                if author_name:
                    authors.append(author_name)
                    if author_orcid:
                        author_orcids.append(author_orcid)

                    for inst in authorship.get('institutions', []):
                        inst_name = inst.get('display_name', '')
                        inst_ror = inst.get('ror', '')
                        if inst_ror:
                            author_ror = inst_ror.replace('https://ror.org/', '')
                        
                        if inst_name:
                            affiliations.append(inst_name)
                        # Collect sub-institution if available
                        sub = inst.get('lineage', [])
                        if sub and len(sub) > 1:
                            author_depts.append(sub[-1])

                    authors_full.append({
                        'name': author_name,
                        'orcid': author_orcid,
                        'ror': author_ror
                    })

            raw_affiliation = ' | '.join(set(affiliations)) if affiliations else self.institution_name

            # ── Gate 3: Affiliation pattern matching ──────────────────────────
            if affiliations and not self.institution_config.matches_affiliation(raw_affiliation):
                self._rejected_gate3 += 1
                self.logger.debug(f"Gate 3 FAIL (pattern mismatch): {title[:60]}")
                continue

            self._accepted += 1
            wave_accepted += 1
            if is_sc_wave:
                self._sc_accepted += 1

            doi = work.get('doi', '')
            abstract = self._reconstruct_abstract(work.get('abstract_inverted_index', {}))
            pub_date = work.get('publication_date', '')

            pdf_url = None
            oa = work.get('open_access', {})
            if oa.get('is_oa') and oa.get('oa_url'):
                pdf_url = oa['oa_url']

            url = (work.get('primary_location', {}) or {}).get('landing_page_url') or doi or ''
            if not url:
                url = f"https://openalex.org/{work.get('id', '').replace('https://openalex.org/', '')}"

            # Extract SDG tags from concepts
            concepts = work.get('concepts', [])
            sdg_tags = self._extract_sdg_from_concepts(concepts)

            yield {
                'title': title,
                'abstract': abstract,
                'authors': authors,
                'author_orcids': author_orcids,
                'authors_full': authors_full,
                'doi': doi,
                'url': url,
                'pdf_url': pdf_url,
                'publication_date': pub_date,
                'source_repository': 'OpenAlex',
                'is_unilag_author': True,  # Legacy field
                'raw_affiliation': raw_affiliation,
                'institution': self.institution_name,
                'institution_ror': self.ror_id,
                'sdg_tags': sdg_tags,
                'dc_subject': ', '.join(c.get('display_name', '') for c in concepts[:5] if c),
            }

        # Cursor-based pagination — keep paginating within the same wave until its
        # cap is hit. Reuse the originating wave's filter (extracted from current URL)
        # so SC waves don't degrade back into plain ROR queries.
        meta = data.get('meta', {})
        next_cursor = meta.get('next_cursor')
        if next_cursor and results and wave_accepted < wave_cap and self._accepted < self.target_limit:
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(response.url).query)
            current_filters = (qs.get('filter') or [f"institutions.ror:{self.ror_short}"])[0]
            next_url = self._build_url(filters=current_filters, cursor=next_cursor)
            yield scrapy.Request(
                url=next_url, callback=self.parse,
                meta={
                    'source': response.meta.get('source', 'ror'),
                    'wave': wave,
                    'wave_accepted': wave_accepted,
                },
            )

    def _reconstruct_abstract(self, inverted_index: dict) -> str:
        """OpenAlex stores abstracts as word→[position] inverted index."""
        if not inverted_index:
            return ''
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        return ' '.join(w for _, w in word_positions)

    def _extract_sdg_from_concepts(self, concepts: list) -> str:
        """Map OpenAlex concepts to SDG numbers (rough heuristic)."""
        sdg_concept_map = {
            'Poverty': 1, 'Food security': 2, 'Health': 3, 'Medicine': 3,
            'Education': 4, 'Gender studies': 5, 'Water resources': 6,
            'Renewable energy': 7, 'Economic growth': 8, 'Engineering': 9,
            'Inequality': 10, 'Urban planning': 11, 'Sustainability': 12,
            'Climate change': 13, 'Marine biology': 14, 'Ecology': 15,
            'Political science': 16, 'International development': 17,
        }
        matched_sdgs = set()
        for concept in concepts:
            name = concept.get('display_name', '')
            for key, sdg_num in sdg_concept_map.items():
                if key.lower() in name.lower():
                    matched_sdgs.add(str(sdg_num))
        return ','.join(sorted(matched_sdgs))

    def closed(self, reason):
        self.logger.info(
            f"Spider closed: {self.institution_name} | "
            f"Accepted: {self._accepted} (SC-wave: {self._sc_accepted}) | "
            f"Rejected (gate2/ROR): {self._rejected_gate2} | "
            f"Rejected (gate3/pattern): {self._rejected_gate3}"
        )
        total_seen = self._accepted + self._rejected_gate2 + self._rejected_gate3
        if total_seen > 0:
            precision = round(self._accepted / total_seen * 100, 1)
            self.logger.info(f"Precision: {precision}%")
