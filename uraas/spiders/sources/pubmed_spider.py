"""
PubMed/NCBI spider — queries the NCBI E-utilities API.

PubMed indexes 37M+ biomedical papers. For URAAS Special Collections it is the
single best source for:
  • Ethnobotany & traditional plant medicine (Indigenous Knowledge category)
  • Traditional healing practices
  • Ethno-pharmacology
  • Community health using indigenous methods

No API key required (1 req/3s). With a free NCBI API key (ncbi.nlm.nih.gov/account/)
the rate limit rises to 10 req/s. Set NCBI_API_KEY in .env.
"""

import os
import sys
from urllib.parse import urlencode

import scrapy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from uraas.config import config
from uraas.config.institutions import get_registry

_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_BATCH   = 100

# Seeds specifically relevant to ethnobotany / traditional medicine SC category
_PUBMED_SEEDS = [
    "ethnobotany", "traditional medicine", "medicinal plants",
    "indigenous knowledge", "traditional healing", "folk medicine",
    "ethnopharmacology", "phytomedicine", "herbal medicine",
    "traditional ecological knowledge",
]


class PubMedSpider(scrapy.Spider):
    name = "pubmed"
    custom_settings = {
        "DOWNLOAD_DELAY": 0.4,  # NCBI etiquette: max 3 req/s without key, 10 with
        "CONCURRENT_REQUESTS": 1,
        "USER_AGENT": f"URAAS/1.0 (+SC discovery; mailto:{config.OPENALEX_MAILTO})",
    }

    def __init__(self, institution="unilag", target=50, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_limit = int(target)
        self.api_key = getattr(config, "NCBI_API_KEY", "") or os.environ.get("NCBI_API_KEY", "")

        registry = get_registry()
        self.institution_config = registry.get(institution)
        if not self.institution_config:
            raise ValueError(f"Institution '{institution}' not found")
        self.institution_name = self.institution_config.name
        self.ror_id = self.institution_config.ror
        self._accepted = 0

    def _affil_term(self) -> str:
        return f'"{self.institution_name}"[Affiliation]'

    def _esearch_url(self, seed: str, retstart: int = 0) -> str:
        term = f'{self._affil_term()} AND "{seed}"[Title/Abstract]'
        params = {
            "db": "pubmed", "term": term, "retmax": _BATCH,
            "retstart": retstart, "retmode": "json",
            "tool": "URAAS", "email": config.OPENALEX_MAILTO,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        return f"{_ESEARCH}?{urlencode(params)}"

    def _efetch_url(self, ids: list) -> str:
        params = {
            "db": "pubmed", "id": ",".join(ids), "rettype": "abstract",
            "retmode": "xml", "tool": "URAAS", "email": config.OPENALEX_MAILTO,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        return f"{_EFETCH}?{urlencode(params)}"

    async def start(self):
        for seed in _PUBMED_SEEDS:
            if self._accepted >= self.target_limit:
                break
            url = self._esearch_url(seed)
            yield scrapy.Request(url=url, callback=self.parse_search,
                                 meta={"seed": seed, "retstart": 0})

    def parse_search(self, response):
        if self._accepted >= self.target_limit:
            return
        data = response.json()
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return
        seed = response.meta["seed"]
        fetch_url = self._efetch_url(ids)
        yield scrapy.Request(url=fetch_url, callback=self.parse_fetch, meta={"seed": seed})

        total = int(data.get("esearchresult", {}).get("count", 0))
        retstart = response.meta["retstart"] + _BATCH
        if retstart < min(total, 500) and self._accepted < self.target_limit:
            next_url = self._esearch_url(seed, retstart)
            yield scrapy.Request(url=next_url, callback=self.parse_search,
                                 meta={"seed": seed, "retstart": retstart})

    def parse_fetch(self, response):
        if self._accepted >= self.target_limit:
            return
        # PubMed efetch returns XML; parse with Scrapy's Selector
        from scrapy import Selector
        sel = Selector(text=response.text, type="xml")

        for art in sel.xpath("//PubmedArticle"):
            if self._accepted >= self.target_limit:
                return
            title = (art.xpath(".//ArticleTitle//text()").getall() or [""])
            title = " ".join(title).strip()
            if not title:
                continue

            abstract = " ".join(art.xpath(".//AbstractText//text()").getall()).strip()

            authors = []
            for auth in art.xpath(".//Author"):
                last = auth.xpath("LastName/text()").get("")
                fore = auth.xpath("ForeName/text()").get("")
                if last:
                    authors.append(f"{fore} {last}".strip())

            pmid = art.xpath(".//PMID/text()").get("")
            doi = art.xpath(".//ELocationID[@EIdType='doi']/text()").get("")

            year = (
                art.xpath(".//PubDate/Year/text()").get("")
                or art.xpath(".//PubDate/MedlineDate/text()").get("")[:4]
            )

            self._accepted += 1
            yield {
                "title": title, "abstract": abstract, "authors": authors, "doi": doi,
                "url": f"https://doi.org/{doi}" if doi else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "pdf_url": None, "publication_date": str(year),
                "source_repository": "PubMed", "is_unilag_author": True,
                "raw_affiliation": self.institution_name, "institution": self.institution_name,
                "institution_ror": self.ror_id,
            }
