# URAAS → UNILAG Institutional Repository: Deployment Readiness & Mounting Plan

**Date:** 2026-06-12
**Status:** NOT YET DEPLOYABLE — blocking issues identified, all remediable in ~1–2 weeks
**Verdict:** Architecturally institutional-grade; operationally requires a security/compliance hardening pass before it touches the UNILAG network.

---

## 1. Executive Summary

URAAS is a multi-institution research-analytics platform (Flask + SQLAlchemy + Flask-SocketIO,
Postgres in production) that harvests bibliographic metadata, classifies it (Special Collections,
African-language research, framework alignment), mints persistent identifiers (DocID/ARK), and
surfaces analytics that are genuinely differentiated from Scopus/SciVal (theme co-occurrence,
knowledge sovereignty, intra-African collaboration, SDG alignment).

**The design and feature set are coherent and institutional-grade.** The reasons it cannot deploy
as-is are operational guardrails, not architecture:

| Blocker | Why it blocks UNILAG deployment |
|---|---|
| **No authentication anywhere** (`app.py:31`, all ~61 routes) | Anyone on the network can start/stop crawlers, flush caches, bulk-export the staff directory and all PDFs. |
| **CORS wildcard on WebSocket** (`app.py:31` `cors_allowed_origins="*"`) | Any external website can connect to the live socket and drive it (CSRF-over-WebSocket). |
| **Uncontrolled PDF serving** (`app.py:256` `download_paper`) | `access_policy`/`dc_rights` is stored but never checked → university becomes an unwitting distributor of possibly-paywalled PDFs (Nigerian Copyright Act exposure). |
| **Google Scholar scraper with proxy rotation** (`scholar_spider.py:49-50` `ProxyGenerator().FreeProxies()`) | Deliberate circumvention of Google ToS / rate limits — a legal and reputational liability for UNILAG. |
| **Faculty scraper ignores robots.txt** (`faculty_directory_spider.py:70` `ROBOTSTXT_OBEY: False`) | Harvests 946 staff names while ignoring the site's machine-readable usage signals. |

Everything below is verified against the source code and against UNILAG's **live** repository server
(not registries) on 2026-06-12.

---

## 2. UNILAG Repository — Verified Live Facts (integration targets)

Probed directly against the running server:

- **Repository UI:** https://ir.unilag.edu.ng/ (Angular, UUID-based)
- **REST backend:** `https://api-ir.unilag.edu.ng/server`
- **Software (authoritative, from the server's own REST root):** **DSpace 9.1** — current generation
  (Java 17 / Tomcat 10 / Spring Boot 3). Registries (ROAR #14321, OpenDOAR #3110) are stale and
  say only "DSpace".
- **OAI-PMH endpoint (LIVE, `Identify` verified):**
  - Base URL: `https://api-ir.unilag.edu.ng/server/oai/request`
  - `repositoryName`: University of Lagos Library
  - `adminEmail`: **dspace@unilag.edu.ng** ← technical contact to approach
  - `earliestDatestamp`: 2015-08-04 (content older than registries claim)
  - `repositoryIdentifier`: `ir.unilag.edu.ng`; protocol 2.0; supports `from`/`until` + `set` for incremental harvest
- **Also live:** full DSpace REST API (`/server/api` — communities, collections, items, bitstreams,
  `discover/search`), OpenSearch/Atom syndication, Solr-backed discovery & statistics.

**Implication:** UNILAG exposes exactly the standards-based, already-public read interfaces URAAS
needs. No internal network access is required to integrate.

---

## 3. How to Mount URAAS — Recommended Architecture

### 3.1 Data integration (read-only, standards-based)

URAAS reads metadata; it does not deposit. That eliminates SWORD entirely.

| Protocol | Use | Recommendation |
|---|---|---|
| **OAI-PMH** (`/server/oai/request`) | Bulk + incremental metadata harvest (`ListRecords` with `from`/`until`, `oai_dc`) | **PRIMARY.** Add a new OAI harvester spider to `uraas/spiders/sources/` (URAAS has none today). Nightly incremental pull. IT approves readily — exposes only already-public metadata. |
| **DSpace REST** (`/server/api`) | Live item-level lookups, `discover/search`, full-text/bitstream access | **SECONDARY / enrichment.** For interactive drill-downs and fields OAI omits. |
| **SWORD** | Deposit INTO repo | **Not applicable** (URAAS analyzes, doesn't deposit). |

**Coverage note:** URAAS already pulls UNILAG output via OpenAlex/Crossref, which often have *broader*
citation/OA coverage than the IR. The IR's unique value is **theses, dissertations and local grey
literature** aggregators miss. Frame OAI harvest as complementary, not a replacement.

### 3.2 Hosting topology (network-safe)

```
Internet ──443──> nginx (TLS termination, analytics.unilag.edu.ng)   [DMZ]
                    │  proxy_http_version 1.1; Upgrade/Connection headers; /socket.io location
                    ▼
                  Gunicorn (eventlet OR gevent, -w 1) under systemd     [bound to 127.0.0.1 only]
                    │
                    ▼
                  Flask + Flask-SocketIO
                    │
        ┌───────────┼─────────────────┐
        ▼           ▼                 ▼
   PostgreSQL    Redis (queue,     egress-only HTTPS to
   (backups)     localhost+auth)   public IR OAI/REST + OpenAlex/Crossref/ORCID
```

**Critical SocketIO deployment facts (the repo has already hit these — see recent gevent/eventlet commits):**
- Async worker is **mandatory** (`--worker-class eventlet` or `gevent`); a sync worker breaks WebSockets.
- **One worker per process** (Gunicorn has no sticky sessions). To scale: multiple `-w 1` processes
  behind nginx `upstream … ip_hash` **+ a Redis message queue** so processes coordinate broadcasts.
- nginx: `proxy_http_version 1.1`, pass `Upgrade`/`Connection "upgrade"`, `proxy_buffering off`,
  dedicated `location /socket.io`; serve static assets from nginx, not Gunicorn.
- systemd: `Restart=always`, dedicated non-root `User=`, `NoNewPrivileges`, `ProtectSystem=strict`,
  `PrivateTmp=true`.

**Why this satisfies UNILAG IT:** the app lives in the **DMZ, never on the internal LAN**, bound to
localhost, with **egress only to public endpoints**. There are no inbound firewall holes into
internal systems and no internal credentials in play. This is the single biggest de-risking fact.

### 3.3 What UNILAG IT will require before sign-off
TLS + HSTS; firewall (443 inbound only); fail2ban + nginx rate limiting; vulnerability scan / pen-test
sign-off; MFA on admin/deploy; audit logging; secrets out of source; Docker or PaaS acceptable but a
university will usually want it in **their own DMZ** rather than a third-party PaaS (so `render.yaml`
is a useful template, not the final target).

---

## 4. Security Findings (verified against source)

### HIGH — must fix before any network deployment
- **H1 — No authentication** (`app.py:31` and all routes). Add Flask-Login/SSO; gate `/api/crawler/*`,
  cache-flush, exports, and staff-directory behind `@admin_required`. Public read-only analytics can
  stay anonymous; everything that writes/controls/exports PII must be authenticated.
- **H2 — Unbounded `limit`/`offset`** on several endpoints (e.g. `app.py:409, 424`) → DoS. Enforce
  hard caps everywhere; add Flask-Limiter (e.g. 100 req/min/IP); add SQLAlchemy query timeouts.
- **H3 — CORS wildcard on SocketIO** (`app.py:31`). Replace `"*"` with explicit allowlist
  (`https://analytics.unilag.edu.ng`).
- **H4 — Weak default SECRET_KEY** (`config.py` fallback `"dev-secret-key"`). Fail startup if
  `DASHBOARD_SECRET_KEY` is unset in production; never ship the literal default.

### MEDIUM — fix before full production
- **M1 — PDF path traversal** (`app.py:263-279`): `file_path` comes from the DB and is `normpath`-joined
  with no containment check. Resolve to realpath and assert it stays under `STORAGE_PATH` before `send_file`.
- **M2 — Cookie flags** only set when `RENDER=true`; on UNILAG they'd be missing. Set
  `SESSION_COOKIE_SECURE/HTTPONLY/SAMESITE` in base config.
- **M3 — XSS via `innerHTML`**: an `esc()` helper exists and is used in many places but not all (40+
  `innerHTML` sinks in `app.js`). Audit each; add a CSP header.
- **M4 — Scrapy pinned `<2.15.0`**: document the compatibility reason; check 2.11–2.14 for CVEs.
- **M5 — LIKE-wildcard injection** in `ilike(f"%{q}%")` (info disclosure / DoS). Escape `%`/`_`,
  cap query length.
- **M6 — No JSON schema validation** on POST bodies (`/api/comparator/*`). Add Pydantic/Marshmallow +
  `MAX_CONTENT_LENGTH`.

### LOW — hardening
- **L1** debug mode on unless `RENDER=true`; **L2** `int()` coercion 500s on bad input (use
  `request.args.get(type=int)`); **L4** rate limiting; **L5** add CSP/security headers.
  (**L3** telnet console already disabled in `crawl_multi_institution.py` — good.)

### Positives already in place
SQLAlchemy ORM throughout (no raw SQL concatenation); env-var config; `esc()` exists; production cookie
flags exist; telnet console disabled; affiliation-validation pipeline; analytics caching.

---

## 5. Legal / Compliance Findings

### BLOCKING (Tier 1)
- **Google Scholar spider** (`scholar_spider.py:49-50`): proxy rotation = deliberate ToS circumvention.
  **Remove it** (OpenAlex/Crossref already cover the same ground).
- **PDF copyright**: enforce `dc_rights`/`access_policy` in the download endpoint; only serve verified
  open-access (gold/hybrid/green via Unpaywall, which the pipeline already classifies but never enforces).
- **robots.txt**: set `ROBOTSTXT_OBEY: True` in `faculty_directory_spider.py:70`; confirm UNILAG pages
  are permitted, or harvest staff lists with explicit institutional permission instead.
- **Privacy notice (NDPA 2023)**: publish one; record lawful basis.

### NDPA 2023 (replaced NDPR 2019; regulator NDPC; GAID directive 2025-03-20)
- Author names, affiliations, ORCIDs, emails = **personal data, in scope** even when published.
- **"Publicly available" is not a blanket exemption** in Nigeria — but processing already-published
  scholarly output for **educational / research / public-interest analytics** is a recognized lawful
  basis. A university analyzing its own scholarly output sits squarely in that zone.
- Still required: data minimization, no sensitive-category scraping, privacy notice, honor
  data-subject requests (author opt-out/correction), keep a lawful-basis record.
- Do **not** borrow India's DPDPA research-exemption wording — Nigeria's NDPA doesn't carry it; rely
  on the educational/public-interest grounds.

### Other
- **Missing `LICENSE` file** for URAAS itself (README says "[Add your license here]") → currently
  "all rights reserved". Choose one (Apache-2.0 recommended) before distribution.
- **ARK test NAAN 99999** (`config.py`, `methodology.py`): fine for now and transparently documented,
  but register a production NAAN (Library of Congress / ARK Alliance, ~4–8 wks, free) before citing
  ARKs externally, so UNILAG isn't linked to non-resolving identifiers.
- **Multi-institution staff configs** (`config/institutions/*.json`): if other universities' staff
  lists are used, get Data Processing Agreements.
- **Crossref/arXiv etiquette**: add contact email to Crossref User-Agent; add `DOWNLOAD_DELAY` +
  honor robots.txt for arXiv.
- Dependency licenses are clean (BSD/MIT/Apache; psycopg2 LGPL is fine via dynamic linking).
  Frontend CDN libs (Chart.js MIT, D3 ISC, MapLibre BSD) clean.

---

## 6. Institutional-Grade Checklist

| Area | Required | Current | Gap |
|---|---|---|---|
| Authentication / SSO | Shibboleth/SAML2 or LDAP for staff; MFA admin | None | **Build** |
| Availability / SLA | Documented target, systemd auto-restart, health probe | `/health` exists | Document SLA |
| Backups | Automated, tested Postgres restores | SQLite committed to git; Postgres path exists | **Move to Postgres + backup drills** |
| Security hardening | TLS, HSTS, fail2ban, rate limit, vuln scan, pen-test | Partial (CI has bandit/pip-audit) | Close §4 items |
| Persistent IDs | Respect DSpace Handles + ORCID; resolvable ARKs | DocID/ARK mint; ORCID spider | Register prod NAAN; link Handles |
| Accessibility | WCAG 2.1/2.2 AA | Not audited | Audit `index.html` + `app.js` (ARIA on live widgets) |
| Monitoring | Uptime, logs, alerting, error tracking | Logs to stdout | Add monitoring/alerting |
| Documentation | Architecture, runbook, lawful-basis register, privacy notice, handover | Partial | Complete handover package |

---

## 7. Phased Plan to Deployable

**Phase 0 — Blocking legal (½ day):** delete `scholar_spider.py`; `ROBOTSTXT_OBEY=True`; enforce
`dc_rights` in `download_paper`; commit a `LICENSE`; draft `PRIVACY_NOTICE.md`.

**Phase 1 — Blocking security (3–5 days):** auth layer (SSO/Flask-Login) on control/PII/export routes;
SocketIO CORS allowlist; fail-fast SECRET_KEY; limit/offset caps + Flask-Limiter; PDF path containment;
base-config cookie flags; CSP + security headers.

**Phase 2 — Integration (3–5 days):** OAI-PMH harvester spider against
`https://api-ir.unilag.edu.ng/server/oai/request` (incremental `from`/`until`); DSpace REST enrichment;
map IR Handles to URAAS records; migrate dev DB to Postgres with backups.

**Phase 3 — Institutional hardening (1–2 wks, partly parallel):** Shibboleth/LDAP SSO; WCAG audit;
monitoring/alerting; register production ARK NAAN (external, ~4–8 wks); pen-test sign-off; handover docs.

**Phase 4 — Deploy:** `analytics.unilag.edu.ng` in DMZ, nginx→Gunicorn(eventlet/gevent `-w 1`)→systemd,
localhost-bound, egress-only. Approach **dspace@unilag.edu.ng** for OAI/REST coordination.

**Realistic time to a safe, sanctioned go-live: ~2 weeks of engineering for Phases 0–2, with Phase 3
items (SSO federation, NAAN registration, pen-test) running in parallel and gating full production.**
