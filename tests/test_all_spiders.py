"""Every paper-sourcing spider can be constructed for a real institution and
carries the attributes the pipeline/dashboard depend on.

Rewritten 2026-08 — the previous version imported uraas.spiders.sources.
scholar_spider (renamed to semantic_scholar_spider long ago) and hardcoded
stale institution/staff counts from early development, so it failed to even
collect and hadn't meaningfully run in a long time.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from uraas.config.institutions import get_registry
from uraas.spiders.sources.ajol_spider import AJOLSpider
from uraas.spiders.sources.arxiv_spider import ArxivSpider
from uraas.spiders.sources.core_spider import CORESpider
from uraas.spiders.sources.crossref_spider import CrossrefSpider
from uraas.spiders.sources.datacite_spider import DataCiteSpider
from uraas.spiders.sources.doaj_spider import DOAJSpider
from uraas.spiders.sources.europepmc_spider import EuropePMCSpider
from uraas.spiders.sources.openaire_spider import OpenAIRESpider
from uraas.spiders.sources.openalex_spider import OpenAlexSpider
from uraas.spiders.sources.orcid_spider import ORCIDSpider
from uraas.spiders.sources.pubmed_spider import PubMedSpider
from uraas.spiders.sources.semantic_scholar_spider import SemanticScholarSpider

SPIDER_CLASSES = {
    "openalex": OpenAlexSpider,
    "crossref": CrossrefSpider,
    "arxiv": ArxivSpider,
    "orcid": ORCIDSpider,
    "semantic_scholar": SemanticScholarSpider,
    "core": CORESpider,
    "openaire": OpenAIRESpider,
    "doaj": DOAJSpider,
    "ajol": AJOLSpider,
    "europepmc": EuropePMCSpider,
    "pubmed": PubMedSpider,
    "datacite": DataCiteSpider,
}


@pytest.fixture(scope="module")
def registry():
    return get_registry()


def test_unilag_is_registered(registry):
    config = registry.get("unilag")
    assert config is not None
    assert config.ror and config.ror.startswith("https://ror.org/")


@pytest.mark.parametrize("spider_name,spider_class", SPIDER_CLASSES.items())
def test_spider_constructs_for_unilag(registry, spider_name, spider_class):
    """Every spider must be constructible against a real institution and
    expose the attributes the pipeline/dashboard read off it afterward."""
    spider = spider_class(institution="unilag")
    assert spider.institution_name == registry.get("unilag").name
    assert spider.ror_id == registry.get("unilag").ror


@pytest.mark.parametrize("spider_name,spider_class", SPIDER_CLASSES.items())
def test_spider_rejects_unknown_institution(spider_name, spider_class):
    with pytest.raises(ValueError):
        spider_class(institution="not-a-real-institution-key")
