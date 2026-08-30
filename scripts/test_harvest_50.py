"""
Test Harvest — UNILAG Special Collections papers (dry run, multi-source).

Discovers SC papers from the open web by querying multiple academic databases:
  • OpenAlex     — broad academic paper index (journals, books, preprints)
  • Crossref     — DOI metadata authority, strong on humanities/social sciences
  • Semantic Scholar — AI-indexed full-text coverage, good for humanities
  • EuropePMC    — PubMed + PMC + WHO; best for ethnobotany / traditional medicine

For each source: queries institution affiliation + SC seed keywords, then applies
the same SC classifier used by the main pipeline. Results are deduplicated by DOI
and normalised title across all sources.

DOES NOT save anything to the local database.
DOES NOT deposit anything to the live DSpace IR.
Safe to run at any time.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from uraas.config import config
from uraas.config.institutions import get_registry
from uraas.config.special_collections import SC_SEED_KEYWORDS
from uraas.services.sc_engine import is_special_collection

_RATE_SLEEP = 1.0  # polite delay between requests per source


# ── OpenAlex ──────────────────────────────────────────────────────────────────


def _reconstruct_abstract(inverted_index: dict) -> str:
    if not inverted_index:
        return ""
    pairs = [
        (pos, word) for word, positions in inverted_index.items() for pos in positions
    ]
    pairs.sort()
    return " ".join(w for _, w in pairs)


def _openalex_url(ror_short: str, seed: str | None, cursor: str = "*") -> str:
    filters = f"institutions.ror:{ror_short}"
    if seed:
        filters += f",title_and_abstract.search:{seed.replace(' ','%20')}"
    return (
        f"https://api.openalex.org/works"
        f"?filter={filters}"
        f"&select=id,doi,title,abstract_inverted_index,authorships,"
        f"publication_date,open_access,primary_location,concepts,type"
        f"&per-page=100&cursor={cursor}&mailto={config.OPENALEX_MAILTO}"
    )


def harvest_openalex(
    session: requests.Session,
    ror_short: str,
    max_results: int,
    seen_dois: set,
    seen_titles: set,
) -> list[dict]:
    papers: list[dict] = []
    seeds = list(SC_SEED_KEYWORDS) + [None]  # None = general ROR wave last

    for seed in seeds:
        if len(papers) >= max_results:
            break
        url = _openalex_url(ror_short, seed)
        page = 0
        while url and len(papers) < max_results:
            page += 1
            try:
                resp = session.get(url, timeout=30)
                resp.raise_for_status()
            except requests.RequestException as exc:
                print(f"  [OA] {seed or 'general'} page {page} err: {exc}", flush=True)
                break
            data = resp.json()
            results = data.get("results", [])
            for work in results:
                if len(papers) >= max_results:
                    break
                title = (work.get("title") or "").strip()
                if not title:
                    continue
                doi = (work.get("doi") or "").replace("https://doi.org/", "").strip()
                norm = title.lower()[:120]
                if doi and doi in seen_dois:
                    continue
                if norm in seen_titles:
                    continue
                abstract = _reconstruct_abstract(
                    work.get("abstract_inverted_index") or {}
                )
                concepts = work.get("concepts") or []
                dc_subject = ", ".join(
                    c.get("display_name", "") for c in concepts[:6] if c
                )
                is_sc, score, cats = is_special_collection(title, abstract, dc_subject)
                if not is_sc:
                    continue
                if doi:
                    seen_dois.add(doi)
                seen_titles.add(norm)
                authors = [
                    a.get("author", {}).get("display_name", "")
                    for a in work.get("authorships", [])
                    if a.get("author", {}).get("display_name")
                ]
                oa = work.get("open_access") or {}
                landing = (work.get("primary_location") or {}).get(
                    "landing_page_url"
                ) or ""
                url_val = landing or (f"https://doi.org/{doi}" if doi else "")
                papers.append(
                    _paper(
                        title,
                        abstract,
                        authors,
                        doi,
                        url_val,
                        oa.get("oa_url") if oa.get("is_oa") else None,
                        work.get("publication_date") or "",
                        work.get("type") or "",
                        score,
                        cats,
                        "OpenAlex",
                    )
                )
                _log_hit(len(papers), score, cats, title)
            meta = data.get("meta") or {}
            next_cursor = meta.get("next_cursor")
            if next_cursor and results and len(papers) < max_results:
                from urllib.parse import parse_qs, urlparse

                qs = parse_qs(urlparse(url).query)
                filt = (qs.get("filter") or [f"institutions.ror:{ror_short}"])[0]
                url = (
                    f"https://api.openalex.org/works?filter={filt}"
                    f"&select=id,doi,title,abstract_inverted_index,authorships,"
                    f"publication_date,open_access,primary_location,concepts,type"
                    f"&per-page=100&cursor={next_cursor}&mailto={config.OPENALEX_MAILTO}"
                )
                time.sleep(_RATE_SLEEP)
            else:
                url = ""
    return papers


# ── Crossref ──────────────────────────────────────────────────────────────────


def harvest_crossref(
    session: requests.Session,
    institution_name: str,
    max_results: int,
    seen_dois: set,
    seen_titles: set,
) -> list[dict]:
    from urllib.parse import quote

    papers: list[dict] = []
    seeds = list(SC_SEED_KEYWORDS) + [None]

    for seed in seeds:
        if len(papers) >= max_results:
            break
        q_seed = f"&query={quote(seed)}" if seed else ""
        url = (
            f"https://api.crossref.org/works"
            f"?query.affiliation={quote(institution_name)}"
            f"{q_seed}"
            f"&select=DOI,title,abstract,author,issued,URL,link"
            f"&rows=50&offset=0&mailto={config.OPENALEX_MAILTO}"
        )
        offset = 0
        while url and len(papers) < max_results:
            try:
                resp = session.get(url, timeout=30)
                resp.raise_for_status()
            except requests.RequestException as exc:
                print(f"  [CR] {seed or 'general'} err: {exc}", flush=True)
                break
            items = resp.json().get("message", {}).get("items", [])
            for work in items:
                if len(papers) >= max_results:
                    break
                title_arr = work.get("title") or []
                title = (title_arr[0] if title_arr else "").strip()
                if not title:
                    continue
                doi = (work.get("DOI") or "").strip()
                norm = title.lower()[:120]
                if doi and doi in seen_dois:
                    continue
                if norm in seen_titles:
                    continue
                abstract = (work.get("abstract") or "").strip()
                is_sc, score, cats = is_special_collection(title, abstract, "")
                if not is_sc:
                    continue
                if doi:
                    seen_dois.add(doi)
                seen_titles.add(norm)
                authors = [
                    f"{a.get('given','')} {a.get('family','')}".strip()
                    for a in work.get("author", [])
                    if a.get("family")
                ]
                issued = work.get("issued", {}).get("date-parts", [[]])[0]
                pub_date = "-".join(str(p) for p in issued) if issued else ""
                pdf_url = next(
                    (
                        lk["URL"]
                        for lk in work.get("link", [])
                        if lk.get("content-type") == "application/pdf"
                    ),
                    None,
                )
                url_val = work.get("URL") or (f"https://doi.org/{doi}" if doi else "")
                papers.append(
                    _paper(
                        title,
                        abstract,
                        authors,
                        doi,
                        url_val,
                        pdf_url,
                        pub_date,
                        "",
                        score,
                        cats,
                        "Crossref",
                    )
                )
                _log_hit(len(papers), score, cats, title)
            offset += 50
            if items and offset < 500 and len(papers) < max_results:
                q_seed2 = f"&query={quote(seed)}" if seed else ""
                url = (
                    f"https://api.crossref.org/works"
                    f"?query.affiliation={quote(institution_name)}"
                    f"{q_seed2}"
                    f"&select=DOI,title,abstract,author,issued,URL,link"
                    f"&rows=50&offset={offset}&mailto={config.OPENALEX_MAILTO}"
                )
                time.sleep(_RATE_SLEEP)
            else:
                url = ""
    return papers


# ── Semantic Scholar ──────────────────────────────────────────────────────────


def harvest_semantic_scholar(
    session: requests.Session,
    institution_name: str,
    max_results: int,
    seen_dois: set,
    seen_titles: set,
) -> list[dict]:
    """
    Semantic Scholar free tier: 1 req/sec (unauthenticated).
    We fire only 3 broad queries instead of one per seed to stay within rate limits.
    Set S2_API_KEY in .env for a higher rate limit (free key at semanticscholar.org).
    """
    from urllib.parse import quote

    from uraas.config import config as cfg

    papers: list[dict] = []
    # Pull API key from env if available
    api_key = getattr(cfg, "S2_API_KEY", "") or os.environ.get("S2_API_KEY", "")
    delay = 1.2 if not api_key else 0.3

    headers = {}
    if api_key:
        headers["x-api-key"] = api_key

    # Use 3 broad queries rather than 20+ per-seed blasts
    broad_queries = [
        f"{institution_name} indigenous knowledge cultural heritage",
        f"{institution_name} postcolonial african literature oral tradition",
        f"{institution_name} ethnobotany traditional medicine decolonial",
    ]

    for query in broad_queries:
        if len(papers) >= max_results:
            break
        offset = 0
        while len(papers) < max_results:
            url = (
                f"https://api.semanticscholar.org/graph/v1/paper/search"
                f"?query={quote(query)}"
                f"&fields=title,abstract,authors,year,externalIds,openAccessPdf"
                f"&limit=100&offset={offset}"
            )
            try:
                time.sleep(delay)
                resp = session.get(url, timeout=30, headers=headers)
                if resp.status_code == 429:
                    # Rate limited — skip remaining S2 queries rather than block.
                    # Add S2_API_KEY to .env (free at semanticscholar.org) to lift limit.
                    print(
                        "  [S2] Rate limited. Add S2_API_KEY to .env for higher quota.",
                        flush=True,
                    )
                    return papers
                resp.raise_for_status()
            except requests.RequestException as exc:
                print(f"  [S2] {query[:40]} err: {exc}", flush=True)
                break
            data = resp.json()
            results = data.get("data", [])
            if not results:
                break
            for work in results:
                if len(papers) >= max_results:
                    break
                title = (work.get("title") or "").strip()
                if not title:
                    continue
                ext = work.get("externalIds") or {}
                doi = (ext.get("DOI") or ext.get("doi") or "").strip()
                norm = title.lower()[:120]
                if doi and doi in seen_dois:
                    continue
                if norm in seen_titles:
                    continue
                abstract = (work.get("abstract") or "").strip()
                is_sc, score, cats = is_special_collection(title, abstract, "")
                if not is_sc:
                    continue
                if doi:
                    seen_dois.add(doi)
                seen_titles.add(norm)
                authors = [
                    a.get("name", "")
                    for a in (work.get("authors") or [])
                    if a.get("name")
                ]
                year = work.get("year")
                oa = work.get("openAccessPdf") or {}
                url_val = f"https://doi.org/{doi}" if doi else ""
                papers.append(
                    _paper(
                        title,
                        abstract,
                        authors,
                        doi,
                        url_val,
                        oa.get("url"),
                        f"{year}-01-01" if year else "",
                        "",
                        score,
                        cats,
                        "Semantic Scholar",
                    )
                )
                _log_hit(len(papers), score, cats, title)
            total = data.get("total", 0)
            offset += 100
            if offset < min(total, 300) and len(papers) < max_results:
                pass
            else:
                break
    return papers


# ── EuropePMC ─────────────────────────────────────────────────────────────────


def harvest_europepmc(
    session: requests.Session,
    institution_name: str,
    affiliation_patterns: list[str],
    max_results: int,
    seen_dois: set,
    seen_titles: set,
) -> list[dict]:
    from urllib.parse import urlencode

    papers: list[dict] = []

    # EuropePMC AFFILIATION field matches against stored author affiliation strings.
    # UNILAG papers appear under several spellings — use a short unambiguous token.
    affil = '(AFFILIATION:"University of Lagos" OR AFFILIATION:"unilag" OR AFFILIATION:"UNILAG")'

    # EuropePMC is best for ethnobotany/traditional medicine SC papers
    priority_seeds = [
        s
        for s in SC_SEED_KEYWORDS
        if any(
            k in s.lower()
            for k in (
                "indigenous",
                "traditional",
                "ethnobotany",
                "cultural",
                "oral",
                "decolonial",
                "ubuntu",
                "ethnomusicology",
            )
        )
    ]

    for seed in priority_seeds:
        if len(papers) >= max_results:
            break
        query = f'{affil} AND ("{seed}")'
        cursor = "*"
        while len(papers) < max_results:
            params = {
                "query": query,
                "format": "json",
                "pageSize": 100,
                "resultType": "core",
                "cursorMark": cursor,
            }
            url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{urlencode(params)}"
            try:
                resp = session.get(url, timeout=30)
                resp.raise_for_status()
            except requests.RequestException as exc:
                print(f"  [EPMC] {seed} err: {exc}", flush=True)
                break
            data = resp.json()
            results = data.get("resultList", {}).get("result", [])
            for r in results:
                if len(papers) >= max_results:
                    break
                title = (r.get("title") or "").strip().rstrip(".")
                if not title:
                    continue
                doi = (r.get("doi") or "").strip()
                norm = title.lower()[:120]
                if doi and doi in seen_dois:
                    continue
                if norm in seen_titles:
                    continue
                abstract = (r.get("abstractText") or "").strip()
                is_sc, score, cats = is_special_collection(title, abstract, "")
                if not is_sc:
                    continue
                if doi:
                    seen_dois.add(doi)
                seen_titles.add(norm)
                pmid = r.get("pmid") or ""
                url_val = (
                    f"https://doi.org/{doi}"
                    if doi
                    else (f"https://europepmc.org/article/med/{pmid}" if pmid else "")
                )
                pdf_url = None
                if r.get("isOpenAccess") == "Y":
                    for ft in (r.get("fullTextUrlList") or {}).get("fullTextUrl") or []:
                        if ft.get("documentStyle") == "pdf":
                            pdf_url = ft.get("url")
                            break
                authors_raw = (r.get("authorList") or {}).get("author") or []
                authors = [
                    f"{a.get('firstName','')} {a.get('lastName','')}".strip()
                    for a in authors_raw
                    if a.get("lastName")
                ]
                papers.append(
                    _paper(
                        title,
                        abstract,
                        authors,
                        doi,
                        url_val,
                        pdf_url,
                        r.get("firstPublicationDate") or r.get("pubYear") or "",
                        r.get("pubType") or "",
                        score,
                        cats,
                        "EuropePMC",
                    )
                )
                _log_hit(len(papers), score, cats, title)
            next_cursor = data.get("nextCursorMark")
            if (
                next_cursor
                and next_cursor != cursor
                and results
                and len(papers) < max_results
            ):
                cursor = next_cursor
                time.sleep(_RATE_SLEEP)
            else:
                break
        time.sleep(_RATE_SLEEP)
    return papers


# ── DOAJ ──────────────────────────────────────────────────────────────────────


def harvest_doaj(
    session: requests.Session,
    institution_name: str,
    max_results: int,
    seen_dois: set,
    seen_titles: set,
) -> list[dict]:
    """
    Directory of Open Access Journals (DOAJ) — covers many African humanities
    and social-science journals that are not in OpenAlex or Crossref.
    Free API, no key required.
    """
    from urllib.parse import quote

    papers: list[dict] = []

    # DOAJ article search: query is full-text across title/abstract/keywords
    priority_seeds = [
        s
        for s in SC_SEED_KEYWORDS
        if any(
            k in s.lower()
            for k in (
                "indigenous",
                "traditional",
                "cultural",
                "oral",
                "postcolonial",
                "decolonial",
                "african",
                "ubuntu",
            )
        )
    ]

    for seed in priority_seeds:
        if len(papers) >= max_results:
            break
        query = f'"{institution_name}" "{seed}"'
        page = 1
        while len(papers) < max_results:
            url = (
                f"https://doaj.org/api/search/articles/{quote(query)}"
                f"?page={page}&pageSize=100"
            )
            try:
                resp = session.get(url, timeout=30)
                resp.raise_for_status()
            except requests.RequestException as exc:
                print(f"  [DOAJ] {seed} err: {exc}", flush=True)
                break
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            for article in results:
                if len(papers) >= max_results:
                    break
                bib = article.get("bibjson") or {}
                title_arr = bib.get("title") or ""
                title = (title_arr if isinstance(title_arr, str) else "").strip()
                if not title:
                    continue
                # DOI from identifiers list
                doi = ""
                for ident in bib.get("identifier") or []:
                    if ident.get("type") == "doi":
                        doi = ident.get("id") or ""
                        break
                norm = title.lower()[:120]
                if doi and doi in seen_dois:
                    continue
                if norm in seen_titles:
                    continue
                abstract = (bib.get("abstract") or "").strip()
                is_sc, score, cats = is_special_collection(title, abstract, "")
                if not is_sc:
                    continue
                if doi:
                    seen_dois.add(doi)
                seen_titles.add(norm)
                authors = [
                    a.get("name", "")
                    for a in (bib.get("author") or [])
                    if a.get("name")
                ]
                pub_date = bib.get("year") or ""
                url_val = f"https://doi.org/{doi}" if doi else ""
                for lnk in bib.get("link") or []:
                    if lnk.get("type") in ("fulltext", "homepage"):
                        url_val = url_val or lnk.get("url", "")
                papers.append(
                    _paper(
                        title,
                        abstract,
                        authors,
                        doi,
                        url_val,
                        None,
                        pub_date,
                        bib.get("journal", {}).get("title", "") or "",
                        score,
                        cats,
                        "DOAJ",
                    )
                )
                _log_hit(len(papers), score, cats, title)
            total = data.get("total", 0)
            if page * 100 < min(total, 500) and len(papers) < max_results:
                page += 1
                time.sleep(_RATE_SLEEP)
            else:
                break
        time.sleep(_RATE_SLEEP)
    return papers


# ── Helpers ───────────────────────────────────────────────────────────────────


def _paper(
    title,
    abstract,
    authors,
    doi,
    url,
    pdf_url,
    pub_date,
    doc_type,
    score,
    cats,
    source,
) -> dict:
    return {
        "title": title,
        "abstract": abstract[:500] + ("…" if len(abstract) > 500 else ""),
        "authors": authors[:5],
        "doi": doi,
        "url": url,
        "pdf_url": pdf_url,
        "publication_date": pub_date,
        "dc_type": doc_type,
        "sc_score": round(score, 1),
        "sc_categories": cats,
        "source": source,
    }


def _log_hit(n: int, score: float, cats: list, title: str):
    safe = title.encode("ascii", errors="replace").decode("ascii")
    print(
        f"  [SC] #{n:>3}  score={score:.1f}  cats={','.join(cats)[:45]}  {safe[:65]}",
        flush=True,
    )


# ── Main harvest orchestrator ─────────────────────────────────────────────────


def harvest_all(
    ror_short: str,
    institution_name: str,
    affiliation_patterns: list[str],
    max_results: int,
) -> list[dict]:
    """
    Fan out across all sources in parallel-quota mode.

    Each source gets an equal quota (max_results // 4, minimum 10). After all
    four sources run, results are merged (deduplicated), sorted by SC score, and
    capped at max_results. This ensures the email reflects genuine multi-source
    coverage rather than being filled by whichever source responds fastest.
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": f"URAAS-TestHarvest/1.0 (dry-run; mailto:{config.OPENALEX_MAILTO})",
            "Accept": "application/json",
        }
    )

    # Per-source quota: each source gets at least 10, up to max_results
    per_source = max(10, max_results // 4)

    # Each source uses its OWN seen sets so they don't clobber each other;
    # dedup across sources happens in the merge step below.
    source_results: dict[str, list[dict]] = {}

    source_fns = [
        (
            "OpenAlex",
            lambda: harvest_openalex(session, ror_short, per_source, set(), set()),
        ),
        (
            "Crossref",
            lambda: harvest_crossref(
                session, institution_name, per_source, set(), set()
            ),
        ),
        (
            "Semantic Scholar",
            lambda: harvest_semantic_scholar(
                session, institution_name, per_source, set(), set()
            ),
        ),
        (
            "DOAJ",
            lambda: harvest_doaj(session, institution_name, per_source, set(), set()),
        ),
    ]

    for source_name, harvest_fn in source_fns:
        print(f"\n[SOURCE] {source_name} (quota: {per_source})", flush=True)
        print("-" * 40, flush=True)
        papers = harvest_fn()
        source_results[source_name] = papers
        print(f"[{source_name}] found {len(papers)} SC papers", flush=True)

    # Merge and deduplicate across sources
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    merged: list[dict] = []

    # Interleave sources (round-robin) so the final list is balanced
    max_src_len = max(len(v) for v in source_results.values()) if source_results else 0
    source_names = list(source_results.keys())
    for i in range(max_src_len):
        for sname in source_names:
            papers = source_results[sname]
            if i >= len(papers):
                continue
            p = papers[i]
            doi = p.get("doi") or ""
            norm = (p.get("title") or "").lower()[:120]
            if doi and doi in seen_dois:
                continue
            if norm and norm in seen_titles:
                continue
            if doi:
                seen_dois.add(doi)
            if norm:
                seen_titles.add(norm)
            merged.append(p)

    # Sort by SC score descending
    merged.sort(key=lambda p: p.get("sc_score", 0), reverse=True)
    return merged[:max_results]


# ── Email ─────────────────────────────────────────────────────────────────────


def send_preview_email(
    to_email: str, institution_name: str, papers: list[dict]
) -> bool:
    from uraas.config import config as cfg

    if not cfg.SMTP_HOST or not cfg.SMTP_USER or not cfg.SMTP_PASSWORD:
        print(
            "[WARN] SMTP not configured — skipping email. Set SMTP_* in .env",
            flush=True,
        )
        preview = json.dumps(papers[:3], indent=2, ensure_ascii=True)
        print(f"       First 3 papers: {preview}", flush=True)
        return False

    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    n = len(papers)
    subject = f"[URAAS] Test Harvest Preview — {n} SC papers from {institution_name}"

    source_counts: dict[str, int] = {}
    for p in papers:
        source_counts[p.get("source", "?")] = (
            source_counts.get(p.get("source", "?"), 0) + 1
        )
    source_summary = " · ".join(f"{s}: {c}" for s, c in sorted(source_counts.items()))

    rows_html = ""
    for i, p in enumerate(papers, 1):
        cats = ", ".join(p["sc_categories"])
        url_part = (
            f'<a href="{p["url"]}" style="color:#3b82f6">{p["url"][:55]}</a>'
            if p["url"]
            else "—"
        )
        pdf_part = (
            f' <a href="{p["pdf_url"]}" style="color:#16a34a;font-size:10px">[PDF]</a>'
            if p.get("pdf_url")
            else ""
        )
        rows_html += f"""
        <tr style="border-bottom:1px solid #e5e7eb">
          <td style="padding:6px 4px;color:#9ca3af;font-size:11px">{i}</td>
          <td style="padding:6px 6px;font-size:12px">
            <strong>{p['title'][:85]}</strong><br>
            <span style="font-size:10px;color:#6b7280">{', '.join(p['authors'][:2])}</span>
          </td>
          <td style="padding:6px 4px;font-size:11px;color:#6b7280">{p.get('dc_type','—')[:20]}</td>
          <td style="padding:6px 4px;font-size:11px;color:#374151">{(p.get('publication_date') or '—')[:4]}</td>
          <td style="padding:6px 4px;font-size:11px;color:#7c3aed">{cats}</td>
          <td style="padding:6px 4px;font-size:10px;color:#2563eb">{p.get('source','?')}</td>
          <td style="padding:6px 4px;font-size:10px">{url_part}{pdf_part}</td>
        </tr>"""

    plain_rows = "\n".join(
        f"{i:>3}. [{p.get('source','?')}] {p['title'][:75]}\n"
        f"     By: {', '.join(p['authors'][:2]) or '—'}  |  {(p.get('publication_date') or '')[:4]}\n"
        f"     SC: {', '.join(p['sc_categories'])}  |  Score: {p['sc_score']}\n"
        f"     URL: {p['url'] or '—'}\n"
        for i, p in enumerate(papers, 1)
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;background:#f9fafb;margin:0;padding:24px">
<div style="max-width:950px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 8px rgba(0,0,0,.1)">
  <div style="background:#1a3a5c;padding:24px 28px">
    <p style="margin:0;font-size:10px;color:#7eb3d4;text-transform:uppercase;letter-spacing:2px">University of Lagos · URAAS</p>
    <h1 style="margin:6px 0 0;font-size:20px;color:#fff">Test Harvest — Special Collections Preview</h1>
    <p style="margin:6px 0 0;font-size:12px;color:#a8c9e0">
      OpenAlex · Crossref · Semantic Scholar · DOAJ · Dry run · No IR deposit
    </p>
  </div>
  <div style="padding:24px 28px">
    <p style="font-size:14px;color:#374151;margin:0 0 12px">
      <strong>Dry-run preview</strong> — no papers were saved to the local database and nothing was
      deposited to the live IR. These are Special Collections papers by <strong>{institution_name}</strong>
      authors discovered from across the open web.
    </p>
    <table style="width:100%;border-collapse:collapse;font-size:13px;margin:0 0 16px">
      <tr style="background:#f3f4f6">
        <td style="padding:8px 6px;font-weight:600">Institution</td>
        <td style="padding:8px 6px">{institution_name}</td>
        <td style="padding:8px 6px;font-weight:600">Total SC papers</td>
        <td style="padding:8px 6px"><strong style="color:#1a7a4a">{n}</strong></td>
      </tr>
      <tr>
        <td style="padding:8px 6px;font-weight:600">Sources</td>
        <td colspan="3" style="padding:8px 6px">{source_summary}</td>
      </tr>
    </table>
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="background:#f3f4f6;text-align:left">
          <th style="padding:6px 4px">#</th>
          <th style="padding:6px 6px">Title / Authors</th>
          <th style="padding:6px 4px">Type</th>
          <th style="padding:6px 4px">Year</th>
          <th style="padding:6px 4px">SC Categories</th>
          <th style="padding:6px 4px">Source</th>
          <th style="padding:6px 4px">URL / PDF</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
    <p style="font-size:12px;color:#6b7280;margin:20px 0 0">
      Papers above were found on the open web and are NOT yet confirmed to be in the UNILAG IR.
      When ready to queue them for IR deposit, use the <strong>IR Deposit</strong> panel in the dashboard.
    </p>
  </div>
  <div style="background:#f0f4f8;padding:14px 28px;font-size:11px;color:#9ca3af;text-align:center">
    URAAS · APA Intelligence &amp; Analytics Platform · University of Lagos · Dry-run — nothing was changed
  </div>
</div>
</body></html>"""

    plain = f"""URAAS Test Harvest — {institution_name}
Sources: {source_summary}
DRY RUN — nothing saved to DB, nothing deposited to IR.

Special Collections papers found: {n}

{plain_rows}
---
URAAS — APA Intelligence & Analytics Platform
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg.SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if cfg.SMTP_USE_TLS:
            srv = smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=30)
            srv.ehlo()
            srv.starttls()
            srv.ehlo()
        else:
            srv = smtplib.SMTP_SSL(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=30)
        srv.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
        srv.sendmail(cfg.SMTP_FROM, [to_email], msg.as_bytes())
        srv.quit()
        print(f"[OK] Email sent to {to_email}", flush=True)
        return True
    except Exception as exc:
        print(f"[ERR] Email failed: {exc}", flush=True)
        return False


def save_json_preview(papers: list[dict], institution: str) -> str:
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "storage",
        f"test_harvest_{institution}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {"institution": institution, "count": len(papers), "papers": papers},
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"[OK] Preview saved to: {out_path}", flush=True)
    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="Multi-source test harvest (dry run — no DB, no IR deposit)"
    )
    parser.add_argument("--institution", default="unilag")
    parser.add_argument(
        "--count", type=int, default=50, help="Max SC papers to collect"
    )
    parser.add_argument("--email", default="lawalgiyath200716@gmail.com")
    args = parser.parse_args()

    registry = get_registry()
    inst_cfg = registry.get(args.institution)
    if not inst_cfg:
        print(f"[ERR] Institution '{args.institution}' not found", flush=True)
        sys.exit(1)

    ror_short = inst_cfg.ror.split("/")[-1]

    print(f"\n{'='*60}", flush=True)
    print(f"URAAS DRY-RUN HARVEST — {inst_cfg.name}", flush=True)
    print(f"Sources: OpenAlex · Crossref · Semantic Scholar · DOAJ", flush=True)
    print(f"{'='*60}", flush=True)

    papers = harvest_all(
        ror_short,
        inst_cfg.name,
        inst_cfg.affiliation_patterns,
        args.count,
    )

    save_json_preview(papers, args.institution)
    send_preview_email(args.email, inst_cfg.name, papers)

    # Source breakdown
    source_counts: dict[str, int] = {}
    for p in papers:
        source_counts[p.get("source", "?")] = (
            source_counts.get(p.get("source", "?"), 0) + 1
        )

    print(f"\n{'='*60}", flush=True)
    print("HARVEST SUMMARY", flush=True)
    print(f"  Institution : {inst_cfg.name}", flush=True)
    print(f"  Total SC    : {len(papers)}", flush=True)
    for src, cnt in sorted(source_counts.items()):
        print(f"    {src:<22}: {cnt}", flush=True)
    print(f"  Email       : {args.email}", flush=True)
    print("  IR deposit  : NOT performed (dry run)", flush=True)
    print(f"{'='*60}\n", flush=True)


if __name__ == "__main__":
    main()
