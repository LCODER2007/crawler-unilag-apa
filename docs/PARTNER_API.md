# URAAS Partner API

Server-to-server read access to URAAS (University of Lagos Academic Archive &
Special Collections) data — built for external partners like the Africa PID
Alliance / DOCiD to integrate against, without needing a browser session.

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
  (partner keys are read-only by construction — no key can reach crawler
  controls, admin exports, or anything that mutates data, regardless of what
  path is requested)
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
Redirects to or streams the PDF, only when the item is open access.

### `GET /api/papers/<id>/bibtex`
BibTeX citation export for one paper (`Content-Type: text/plain`).

### `GET /api/analytics/special-collections`
The Special Collections subset specifically — the papers classified into one
or more of the 8 categories (Indigenous Knowledge, Cultural Heritage, Oral
Tradition, Ethnomusicology, African Philosophy, Traditional Medicine, Ethnic
Languages & Groups, Pan-African Studies).

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
The full registry of institutions URAAS crawls against (52 African
universities as of this writing) — name, ROR, country.

### `GET /api/institution/info?institution=unilag`
Summary for one institution from the registry above. `institution` is the
registry key (e.g. `unilag`); omitting it returns null fields.

```json
{ "status": "success", "data": { "institution_name": "University of Lagos", "country_name": "Nigeria", "country_code": "NG" } }
```

---

## Example

```bash
curl -H "X-API-Key: uraas_live_..." \
  "https://lordkiki-apa-uraas.hf.space/api/analytics/special-collections/overview"
```

---

## What this API does *not* do (yet)

There is currently no inbound path — nothing lets DOCID's platform push data
or notifications back into URAAS (e.g. "here's the DocID we just assigned,
sync your record" or a webhook on registration). Every endpoint above is
URAAS serving data out. If two-way sync is needed, that's new work to scope
separately, not something already exposed here.

## For URAAS admins — issuing/revoking keys

```bash
python scripts/manage_api_keys.py create --name "Africa PID Alliance / DOCiD"
python scripts/manage_api_keys.py list
python scripts/manage_api_keys.py revoke --prefix uraas_live_AbCd1234
```

The full key value is shown exactly once, at creation — only its hash is
stored. If a key is lost or compromised, revoke it and issue a new one; there
is no way to recover a lost key's value.

To add a new endpoint to partner access, add its Flask endpoint (function)
name to `PARTNER_ENDPOINTS` in `uraas/dashboard/app.py` — nothing is reachable
via API key unless explicitly listed there.
