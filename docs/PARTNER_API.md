# URAAS Partner API

Server-to-server access to URAAS (University of Lagos Academic Archive &
Special Collections) data — built for external partners like the Africa PID
Alliance / DOCiD to integrate against, without needing a browser session.
Mostly read (papers, Special Collections, analytics); one narrowly-scoped
action (triggering a UNILAG crawl) is also available.

This is separate from the dashboard's human login (username/password +
session cookie). Partner access uses a long-lived API key instead.

---

## Base URL

```
https://lordkiki-apa-uraas.hf.space
```

## Authentication

Every request must include the key in a header:

```
X-API-Key: uraas_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

- Missing or invalid key → `401 Unauthorized`
- Valid key used against an endpoint outside this document → `403 Forbidden`
  (a key only ever reaches the endpoints listed here, by construction — the
  admin crawler console, bulk exports, and anything else that mutates data
  stay 403 regardless of what path is requested)
- Keys are issued manually by a URAAS admin. To request one, contact the
  URAAS team directly — there is no self-service signup.

## Rate limits

**120 requests per rolling 60-second window, per key.** Exceeding it returns
`429 Too Many Requests`. Contact us if your integration needs a higher limit.

## Errors

All errors are JSON:

```json
{ "status": "error", "message": "..." }
```

| Status | Meaning |
|---|---|
| `401` | Missing or invalid/revoked API key |
| `403` | Valid key, but this endpoint isn't in the partner allowlist |
| `429` | Rate limit exceeded |
| `404` | Resource not found (e.g. unknown paper id) |
| `500` | Server error — please report it to us |

---

## Record identity — read this before building an ingest

**Key on `doi` where present; treat `id` as a local handle, not a stable
identifier.**

`id` is a database primary key. Records are deleted by real admin
operations (the dashboard's prune and clear-half-recrawl actions), and the
live deployment runs on SQLite, where a plain `INTEGER PRIMARY KEY` can
reuse the id of a deleted row. So an id can 404 later (the gaps you'd see in
any id range are these deletions), and in the worst case a reused id would
point at a *different* paper — silently producing a duplicate on your side
rather than an error.

- `doi` — present on the large majority of records, and the right join key.
- `url` — always present; stable per record and usable as a fallback.
- `docid` — the real registered DOCiD once assigned, empty string otherwise.

There is currently no separate immutable `(source, record_id)` external key.
If you need one, say so — `source_repository` plus the source's own
identifier is recorded internally for most sources and could be exposed.

## Scope — what's actually in here

- **Discovery records, not a repository mirror.** Most records are
  third-party index entries (OpenAlex, Crossref, PubMed, DOAJ, OpenAIRE,
  DataCite, Semantic Scholar, ORCID) for papers by authors affiliated with
  the institution — not items held in the institution's own repository. A
  minority (`source_repository: "UNILAG IR (OAI-PMH)"`) *are* harvested from
  UNILAG's repository. The `source_repository` field distinguishes them.
- **The database is multi-institution.** URAAS is built to serve several
  institutions; records carry `institution`/`ror`. The partner crawl trigger
  is locked to UNILAG, but that doesn't change what earlier crawls already
  stored — expect more than one custodian institution in aggregate views.
- **ARKs are sandbox identifiers.** Records minted before 2026-08 carry
  `ark:/99999/...`. 99999 is the reserved ARK test NAAN, so these do **not**
  resolve publicly — treat them as internal keys, not persistent
  identifiers. Local ARK minting has since been removed (identifiers should
  come from a real authority, not be self-issued). A registered NAAN would
  have to be applied for before any ARK here is citable.

---

## Endpoints

### `GET /api/stats`
Network/collaboration summary: co-authorship edges between departments, and
top authors by paper count.

```json
{
  "status": "success",
  "network_edges": [{ "source": "Botany", "target": "Chemistry", "weight": 1 }],
  "top_authors": [{ "author": "...", "count": 2, "orcid": "", "ror": "" }]
}
```

### `GET /api/papers/tree`
Every paper, grouped by faculty then department.

**A paper appears once per department it is linked to**, so the row count
exceeds the distinct paper count (papers ↔ departments is many-to-many, and
cross-departmental co-authorship is common). Rows for the same paper carry
identical content — de-duplicate on `id` or `doi`. This is structural rather
than a bug, but it does mean row counts are not paper counts.

```json
{
  "data": {
    "College of Medicine": {
      "Community Health and Primary Care": [
        {
          "id": 22,
          "title": "...",
          "doi": "10.1093/hmg/ddw104",
          "url": "https://doi.org/10.1093/hmg/ddw104",
          "docid": "",
          "download_url": null,
          "has_local_pdf": false,
          "access_policy": null
        }
      ]
    }
  }
}
```
`docid` is populated once a paper has a real, registered DOCiD — empty string
otherwise. This is the field to poll if you want to detect which URAAS papers
already carry a DOCiD vs. which don't yet.

### `GET /api/papers/<id>`
Full metadata for one paper — title, abstract, authors, DOI, publication
date, Special Collections category/score, and identifiers (`docid`, `ark`,
`ror`) where present.

### `GET /api/papers/<id>/download`
Streams the PDF, only for items that are open access **and** have a locally
stored file. Most records have no local PDF at all (URAAS stores metadata
for everything it discovers, but only downloads full text where a licence
permits), so expect `404` far more often than `200`.

Note (fixed 2026-09): this endpoint previously returned `403` for *every*
item, including genuinely open-access ones. `Item.dc_rights` had a model
default of `restrictedAccess` and no code path ever wrote it, so the
download gate — and every open-access metric in the API — read a field that
was permanently unset. Sources' own OA signals are now recorded at crawl
time, and existing records have been backfilled from Unpaywall.

### `GET /api/papers/<id>/bibtex`
BibTeX citation export for one paper (`Content-Type: text/plain`).

### `GET /api/analytics/special-collections`
The Special Collections records. The 8 categories are exactly:

1. Indigenous Knowledge
2. African Literature
3. Cultural Heritage
4. Ethnic Languages & Groups
5. Postcolonial Studies
6. Pan-African Studies
7. African Philosophy
8. Ethnomusicology

Corrected 2026-09: earlier revisions of this document listed "Oral
Tradition" and "Traditional Medicine", which are **not** categories (they
are seed terms the crawler searches on, which is where the confusion came
from), and omitted African Literature and Postcolonial Studies, which are.
The authoritative list is `SPECIAL_COLLECTIONS` in
`uraas/config/special_collections.py`.

**Every record in URAAS carries at least one of these, by design** — this is
a curated collection, not a tagging layer over a general corpus. All 13
discovery spiders apply the Special Collections classifier *before* an item
is ever stored (`sc_score_of(...) <= 0` → discarded), so a paper that isn't
Special Collections never enters the database at all.

### `GET /api/analytics/special-collections/overview`
Aggregate view over that same set: category co-occurrence matrix, country
breakdown, custodian institutions, and the most-cited/influential papers per
category.

```json
{
  "co_occurrence": { "labels": [...], "matrix": [[...]] },
  "countries": [{ "code": "NG", "name": "Nigeria", "papers": 54 }],
  "custodians": [{ "institution": "University of Lagos", "count": 54 }],
  "influential": [{ "id": 1, "title": "...", "categories": [...], "citations": 856, "sc_score": 3.0 }]
}
```

### `GET /api/university-registry`
The registry of institutions URAAS can crawl against — key, name, ROR,
country, sub-region.

```json
{ "status": "success", "count": 43,
  "data": [{ "key": "UNILAG", "name": "University of Lagos",
             "ror": "https://ror.org/05rk03822",
             "country": "Nigeria", "sub_region": "West Africa" }] }
```

`key` is what `/api/institution/info?institution=` expects (case-insensitive).

Fixed 2026-09: this returned `500` because it read
`data/university_registry.json`, a file that never existed in the repo. It
now serves the live registry the crawler itself uses, so the two can't drift
apart. The count is **43**, not the 52 previously documented — 10
institutions had duplicate config entries under different short names
(Addis Ababa, Cairo, Makerere, Stellenbosch and others each appeared twice),
which also explains any duplicate institutions seen in earlier responses.
Those have been merged.

### `GET /api/institution/info?institution=unilag`
Summary for one institution from the registry above. `institution` is the
registry key (e.g. `unilag`); omitting it returns null fields.

```json
{ "status": "success", "data": { "institution_name": "University of Lagos", "country_name": "Nigeria", "country_code": "NG" } }
```

### `POST /api/partner/crawl/start`
Trigger a fresh UNILAG crawl yourself, instead of waiting on someone to run
one from the dashboard. Deliberately narrower than the internal admin
trigger — a crawl fans out to a dozen third-party APIs and can end in real
DOCiD registrations, so nothing partner-triggered is unrestrained:

- **Institution is always `unilag`** — not a request field, can't be overridden.
- **`target`** — papers to find, 1–50 (default 20). Higher targets aren't available via this endpoint.
- **`spider`** — one of `openalex`, `crossref`, `arxiv`, `orcid`, `semantic_scholar`, `europepmc`, `core`, `pubmed`, `openaire`, `doaj`, `ajol` (default `openalex`).
- **`boost_special`** — bias the crawl toward Special Collections (default `true`).
- **Cooldown: one trigger per key per 10 minutes**, independent of the 120/min general rate limit and independent of whether a crawl happens to be running.

```json
{ "target": 20, "spider": "openalex", "boost_special": true }
```

```json
{ "status": "success", "message": "Crawl started — target 20 papers (UNILAG, openalex)" }
```

A crawl already running (triggered by anyone — admin or partner) → `400`.
Cooldown still active → `429` with seconds remaining.

### `GET /api/partner/crawl/status`
`{"status": "running"}` or `{"status": "idle"}`. Poll this after triggering a
crawl, then re-pull from the read endpoints above once it's idle again.

---

## Example

```bash
curl -H "X-API-Key: uraas_live_..." \
  "https://lordkiki-apa-uraas.hf.space/api/analytics/special-collections/overview"
```

---

## What this API does *not* do (yet)

**No citation edge list.** Records carry `cited_by_count` and
`counts_by_year` (aggregate counts only) — there is nothing describing what
a given paper cites or what cites it. Anything built on a citation graph
(e.g. "related records") cannot be served from this API today. OpenAlex
does expose `referenced_works` per work and URAAS already queries OpenAlex,
so capturing it is feasible, but it is not currently stored and would be new
work.

**No inbound sync.** Triggering a crawl is the only inbound action. There is
no webhook for "here's the DocID we assigned, update your record." Every
other endpoint is URAAS serving data out.

**Direction of travel.** As of 2026-09 the agreed model is that DOCiD
*pulls* from URAAS into its own staging, where a curator promotes records.
URAAS's automatic push-to-DOCiD after each crawl is therefore **disabled by
default** (`URAAS_ENABLE_DOCID_PUSH`), so the same records can't be ingested
twice from both directions.

## For URAAS admins — issuing/revoking keys

Two equivalent paths — a CLI for local/shell access, and an HTTP path (admin
session required) for a deployed instance with no shell, like the HF Space:

```bash
python scripts/manage_api_keys.py create --name "Africa PID Alliance / DOCiD"
python scripts/manage_api_keys.py list
python scripts/manage_api_keys.py revoke --prefix uraas_live_AbCd1234
```

```
POST   /api/admin/api-keys              { "name": "..." }
GET    /api/admin/api-keys
POST   /api/admin/api-keys/<id>/revoke
```

The full key value is shown exactly once, at creation — only its hash is
stored. If a key is lost or compromised, revoke it and issue a new one; there
is no way to recover a lost key's value.

To add a new endpoint to partner access, add its Flask endpoint (function)
name to `PARTNER_ENDPOINTS` in `uraas/dashboard/app.py` — nothing is reachable
via API key unless explicitly listed there.
