"""
Dedup-aware crawling mixin — fixes the "same papers every crawl" bug.

Root cause: every web-discovery spider counted an item toward its `target`
the moment it passed the Special-Collections gate, without ever checking
whether the item already existed in the DB. Source APIs return deterministic
ordering for identical queries, so every repeat run re-fetched the same
shallow window of results, "filled" target with items the pipeline then
silently dropped as duplicates (see uraas/pipelines/database.py dedup
logic), and stopped paginating before reaching genuinely new material
deeper in the source.

DedupAwareSpiderMixin loads a snapshot of known DOIs/URLs/titles once per
spider run and lets each spider skip (not count, but keep paginating past)
items already in the DB — so `target` means "N genuinely new SC papers",
and repeat runs actually make progress instead of asymptoting to zero.

Normalization here MUST match uraas/pipelines/database.py's dedup checks
exactly (DOI stripped of doi.org prefixes; title lowercased, compared on
the full string up to the column's max length) so spider-side prediction
agrees with pipeline-side outcome.
"""

from typing import Optional

from scrapy.exceptions import CloseSpider

_TITLE_MAX_LEN = 512  # matches Item.title = Column(String(512))


def _norm_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    return (
        doi.replace("https://doi.org/", "").replace("http://dx.doi.org/", "").strip()
    ) or None


def _norm_title(title: Optional[str]) -> Optional[str]:
    if not title:
        return None
    return title.strip().lower()[:_TITLE_MAX_LEN] or None


class DedupAwareSpiderMixin:
    """Mix into a scrapy.Spider subclass alongside the spider's normal base.

    Usage:
        class MySpider(DedupAwareSpiderMixin, scrapy.Spider):
            def __init__(self, ...):
                super().__init__(...)
                ...
                self._init_dedup_index()   # call last, after institution_config etc.

    Then in the per-item loop, right before incrementing the accepted
    counter and yielding:

        if self._is_known(doi=doi, url=url, title=title):
            continue                      # already ingested — keep paginating
        self._accepted += 1
        ...
        yield item
        self._mark_seen(doi=doi, url=url, title=title)
    """

    def _init_dedup_index(self):
        """Load a global snapshot of known DOIs/URLs/titles once per run.

        Global (not institution-scoped) to match the pipeline's own dedup,
        which has no institution filter — an institution-scoped index here
        could let a spider "accept" a paper the pipeline still silently
        drops as a cross-institution duplicate.
        """
        from uraas.database import Item, SessionLocal

        session = SessionLocal()
        try:
            self._seen_dois = {
                d for (d,) in session.query(Item.doi).filter(Item.doi.isnot(None))
            }
            self._seen_urls = {
                u for (u,) in session.query(Item.url).filter(Item.url.isnot(None))
            }
            self._seen_titles = {
                _norm_title(t) for (t,) in session.query(Item.title) if t
            }
        finally:
            session.close()
        self._skipped_known = 0
        self.logger.info(
            "Dedup index loaded: %d DOIs, %d URLs, %d titles",
            len(self._seen_dois), len(self._seen_urls), len(self._seen_titles),
        )

    def _is_known(
        self,
        *,
        doi: Optional[str] = None,
        url: Optional[str] = None,
        title: Optional[str] = None,
    ) -> bool:
        """True if this item is already in the DB (by DOI, URL, or exact title)."""
        d = _norm_doi(doi)
        if d and d in self._seen_dois:
            self._skipped_known += 1
            return True
        if url and url in self._seen_urls:
            self._skipped_known += 1
            return True
        t = _norm_title(title)
        if t and t in self._seen_titles:
            self._skipped_known += 1
            return True
        return False

    def _mark_seen(
        self,
        *,
        doi: Optional[str] = None,
        url: Optional[str] = None,
        title: Optional[str] = None,
    ):
        """Record a newly-accepted item so multi-wave spiders (e.g. OpenAlex's
        ~20 SC seed-keyword waves) don't double-count the same paper within
        one run."""
        d = _norm_doi(doi)
        if d:
            self._seen_dois.add(d)
        if url:
            self._seen_urls.add(url)
        t = _norm_title(title)
        if t:
            self._seen_titles.add(t)

    def _stop_if_target_reached(self):
        """Call at the top of parse() once `self._accepted >= self.target_limit`.

        Every SC-seed-wave spider builds its full set of seed requests
        up-front in `async def start()` — that generator runs to completion
        in a single event-loop tick (no `await` inside it), so it enqueues
        every wave's request with the scheduler before a single response has
        come back and `self._accepted` has had any chance to update. A plain
        `return` inside parse() only stops *processing* an already-downloaded
        response; every other already-scheduled request still gets sent over
        the network regardless. With SC_SEED_KEYWORDS now covering the full
        (ambiguity-filtered) taxonomy (~300 seeds, up from ~20), that "keep
        firing queued requests we don't need" tail became the dominant cost
        of a crawl — live-tested on openalex_spider.py: target=15 was
        satisfied by items found within the first ~2.5 minutes, but the run
        kept making network requests for another ~20+ minutes draining the
        rest of the queue. Raising CloseSpider here tells the engine to
        actually cancel the remaining scheduled-but-undispatched requests.
        """
        raise CloseSpider(reason="target reached")
