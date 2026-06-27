# Mounting URAAS alongside the UNILAG Institutional Repository — Operations & Safety Guide

**Audience:** UNILAG ICT/Library systems team and the URAAS deployment engineer.
**Last verified:** 2026-06-17 — written by reading the **actual source code**, not prior
design notes. Where this guide disagrees with `UNILAG_DEPLOYMENT_READINESS.md`, trust this
one: it reflects what the code does today.

---

## 0. What URAAS actually is (from the code)

URAAS is a self-contained **Flask + Flask-SocketIO** web app (`uraas/dashboard/app.py`)
with a **built-in Scrapy crawler** and a local database. It has four moving parts:

1. **Dashboard / API** — Flask app, ~60 routes, served by Gunicorn behind nginx.
2. **Crawler** — a Scrapy process (`scripts/crawl_multi_institution.py`) launched as a
   **subprocess** by the admin-only route `/api/crawler/start` (`app.py:2148`). Its live
   log is streamed to the browser over WebSocket.
3. **Local datastore** — SQLite (dev) / PostgreSQL (prod) + a PDF folder, both on the
   URAAS host. The crawler writes here via `DatabaseStoragePipeline`
   (`uraas/pipelines/database.py`).
4. **Analytics/services** — comparator, special-collections engine, alignment, etc., all
   reading the local DB.

**This is the single most important fact for the UNILAG repository team:**

> **The crawler does not read from, write to, or connect to the UNILAG repository server
> (`ir.unilag.edu.ng` / `api-ir.unilag.edu.ng`) at all.** I traced every spider's target
> host (see §2). URAAS discovers UNILAG's research output from *global aggregators*,
> filtered by UNILAG's ROR identifier. The IR server receives zero traffic from URAAS.

So "mounting on the UNILAG IR" does **not** mean installing anything into DSpace or pointing
the crawler at the repository. It means: **stand URAAS up as its own service** (optionally
on a UNILAG-controlled host / subdomain), and **optionally** add a link from the IR's UI to
the URAAS dashboard. Two further, optional integration levels are described in §4.

---

## 1. Where the crawler actually goes — verified per spider

Every spider and its real target host, read from the source:

| Spider (`uraas/spiders/sources/`) | Connects to | Touches UNILAG infra? |
|---|---|---|
| `openalex_spider.py` | `api.openalex.org/works?filter=institutions.ror:<UNILAG ROR>` | **No** |
| `crossref_spider.py` | `api.crossref.org/works` | **No** |
| `arxiv_spider.py` | `arxiv.org` (`allowed_domains = ["arxiv.org"]`) | **No** |
| `orcid_spider.py` | `pub.orcid.org/v3.0/...` | **No** |
| `faculty_directory_spider.py` | `science.unilag.edu.ng`, `engineering.unilag.edu.ng`, … (faculty **public websites**) | **UNILAG public sites — but NOT the IR** |

**How discovery works (the OpenAlex spider, the default):** it queries OpenAlex for works
whose author institution ROR == UNILAG's ROR (`institutions.ror:05rk03822`), then applies
4 precision gates (ROR-in-authorships, affiliation-string match, AI special-collections
classifier) before keeping a record (`openalex_spider.py:116-255`). The institution ROR
comes from `config/institutions/unilag.json`. No UNILAG login, no IR endpoint.

**The one place URAAS touches UNILAG-owned servers** is the *faculty directory* spider,
which scrapes **faculty public web pages** (not the IR) to build the staff name list. It is
polite by construction (`faculty_directory_spider.py:68-75`): `DOWNLOAD_DELAY = 1.5`,
**`ROBOTSTXT_OBEY = True`**, `RETRY_TIMES = 2`, and a descriptive `User-Agent` carrying
`mailto:library@unilag.edu.ng`. This spider is not part of the default dashboard crawl
(the dashboard runs OpenAlex via `crawl_multi_institution.py`); it's a separate staff-list
build step.

---

## 2. Why nothing can ever happen to the UNILAG repository server

Each guarantee is tied to a concrete, code-verifiable fact.

### 2.1 URAAS has no code path to the IR at all
- There is **no OAI-PMH client, no DSpace REST client, no SWORD client** in the codebase.
  Grep for `oai`, `dspace`, `ir.unilag` returns only `database.py` (a string field) and a
  backfill script — **no spider, no request, no connection**.
- Therefore URAAS cannot read, write, delete, or overload the repository, because it never
  contacts it. The repository's safety does not even depend on URAAS being well-behaved.

### 2.2 It cannot overload anything it *does* touch
- Aggregator spiders are throttled in `custom_settings`: OpenAlex uses `DOWNLOAD_DELAY=1.0`
  + AutoThrottle + `CONCURRENT_REQUESTS=1` (`openalex_spider.py:30-36`); Crossref/arXiv/ORCID
  similarly delayed; all send a contact `mailto` so they sit in providers' "polite pools".
- The faculty-site spider obeys `robots.txt` and waits 1.5s between requests.
- Crawl size is **bounded**: `/api/crawler/start` clamps `target` to `min(max(t,1),250)`
  (`app.py:2157`), and the spider hard-stops at the target (`openalex_spider.py:120,136`).
- Only **one** crawler subprocess can run at a time — guarded by `crawler_lock` +
  `crawler_process.poll()` (`app.py:2150-2155`).

### 2.3 It runs on a separate host with no inbound path into UNILAG internals
```
Internet ──443──► nginx (TLS, analytics.unilag.edu.ng)        [DMZ host]
                    ▼  proxies /, /socket.io; rate-limits /login
                  Gunicorn (gthread)  ── bound to 127.0.0.1 only
                    ▼
                  Flask app  ──spawns──►  Scrapy subprocess (the crawler)
                    │                          │  egress-only HTTPS to:
                    ▼                          ▼  api.openalex.org, api.crossref.org,
              local DB + PDFs            arxiv.org, pub.orcid.org, *.unilag.edu.ng faculty sites
            (on the URAAS host)          (NEVER ir.unilag.edu.ng)
```
- The app binds to `127.0.0.1`; the outside world only reaches nginx on 443.
- All crawler traffic is **outbound** to **public** endpoints. **No inbound firewall hole**
  into any internal UNILAG system; **no UNILAG/DSpace credentials** anywhere in the code.

### 2.4 The dashboard itself is fail-closed and hardened (verified in code)
- **Auth is fail-closed by endpoint name** (`app.py:110-120`): a single `before_request`
  gate; any new route is protected until explicitly allowlisted. Only
  `login/logout/health_check/api_version/static` are public. **Crawler control, exports,
  and the staff directory (PII) are admin-only** (`ADMIN_ENDPOINTS`, `app.py:93-107`).
- **WebSocket requires a logged-in session** (`@socketio.on("connect")`, `app.py:246-252`)
  — the crawler stream can't be driven anonymously; CORS is an explicit allowlist, no `*`.
- **Config fails fast in prod** (`config/__init__.py: validate()`): startup aborts on the
  default `SECRET_KEY` or a missing `ADMIN_PASSWORD_HASH`.
- **PDF serving is path-contained + copyright-gated** (`download_paper`, `app.py:424-486`):
  realpath-asserted under the storage root (no traversal), and non-open-access items are
  blocked for non-admins (`_is_open_access`).
- **Security headers / CSP / HSTS** (`app.py:219-243`); **login rate-limiting** via
  Flask-Limiter + an nginx `limit_req` second layer; **clamped int inputs** (`clamped_int`).

### 2.5 The abusive component is already gone
- The old Google-Scholar spider (rotating free proxies = ToS circumvention) has been
  **deleted** — `uraas/spiders/sources/` contains only the five well-behaved spiders above.

**Net:** under any failure or breach of URAAS, the blast radius is the URAAS host. The IR
is untouched because URAAS never connects to it and holds no credentials to it.

---

## 3. It is lightweight

| Resource | Footprint (from the code/deps) |
|---|---|
| Process model | One Gunicorn app (`gthread`, matches `async_mode="threading"`) + a short-lived crawler subprocess. No microservices. |
| Datastore | One SQLite/PostgreSQL DB + a PDF folder on the URAAS host. |
| Memory | Comfortable in 1–2 GB; 2 vCPU ample. |
| Heavy deps | Optional only: spaCy/embedding model for classification; Redis only if you scale to multiple workers. No Elasticsearch/Kafka/Spark. |
| Disk guard | `STORAGE_MIN_FREE_GB` prevents filling the disk. |
| Load on IR | **Zero** (no IR connection). Load on aggregators: minimal, throttled, polite-pool. |

A 2 vCPU / 4 GB / 40 GB VM runs the whole platform with headroom.

---

## 4. Three ways to "mount" it — pick the level UNILAG wants

### Level 0 — Standalone (works today, recommended first step)
Deploy URAAS as its own service (§5). It already discovers UNILAG's research via ROR on the
aggregators. The IR is not involved at all. Optionally add one `<a href>` from the IR UI to
`https://analytics.unilag.edu.ng`. **Zero risk to the IR, zero IR-side work.**

### Level 1 — Read-only IR harvest (implemented: `oai_spider.py`)
To index theses/grey literature the aggregators miss, URAAS now ships a **read-only OAI-PMH
harvester** at `uraas/spiders/sources/oai_spider.py`. UNILAG's OAI endpoint is live and
public (re-probed 2026-06-17): base URL `https://api-ir.unilag.edu.ng/server/oai/request`,
protocol 2.0, datetime granularity, admin `dspace@unilag.edu.ng`, and it is set in
`config/institutions/unilag.json` as `oai_endpoint`. OAI-PMH is **read-only by protocol** —
it has no verbs that mutate data — so this cannot harm the IR.

**How it behaves (verified against the live server):**
- Issues only `ListRecords` GETs (`metadataPrefix=oai_dc`) and follows `resumptionToken`
  pages — no writes, no credentials, no bitstream downloads (metadata + Handle URL only).
- **Always bounded** with a `from` lower bound (the unbounded full harvest times the server
  out with a 500, so a date window is mandatory and defaults to a recent look-back).
- Polite: `DOWNLOAD_DELAY=2.0`, `CONCURRENT_REQUESTS=1`, AutoThrottle, `ROBOTSTXT_OBEY=True`,
  and a contact `User-Agent` so the IR admin can identify URAAS traffic.
- Harvested records flow through the same `DatabaseStoragePipeline`, which keeps only
  Special-Collections-scored items — exactly the local material aggregators omit.

**Run it** (from the dashboard's admin crawler with `{"spider":"oai","from_date":"2026-01-01"}`,
or on the CLI):
```bash
python scripts/crawl_multi_institution.py --spider oai --institutions unilag \
    --target 200 --from-date 2026-01-01            # --until-date optional
```
Coordinate the harvest window with `dspace@unilag.edu.ng` and schedule it incrementally
(nightly `--from-date <yesterday>`) off-peak.

### Level 2 — Embedded in the IR page (cosmetic)
Surface a URAAS analytics widget inside the IR via an iframe/link. Note URAAS sends
`X-Frame-Options: DENY`, so embedding requires relaxing that to `frame-ancestors` for the IR
origin — a deliberate, reviewed change. Still no write path to the IR.

---

## 5. Step-by-step deployment (Level 0)

> Run on the **URAAS host** (DMZ VM/container), never on the repository server.

### Phase A — Host & network
1. Provision a DMZ VM (Ubuntu LTS, 2 vCPU / 4 GB / 40 GB), dedicated non-root user.
2. Firewall: **inbound 443 only**; **outbound 443** allowed (aggregators + faculty sites).
3. DNS: `analytics.unilag.edu.ng` → host IP.

### Phase B — Install
```bash
git clone <uraas-repo-url> /opt/uraas && cd /opt/uraas
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm   # classifier model (see Dockerfile)
```
*(Or use the shipped `Dockerfile` / `docker-compose.prod.yml`.)*

### Phase C — Environment (security-critical) — copy `.env.example` → `.env`
```bash
URAAS_ENV=production                      # turns on validate(), secure cookies, HSTS
DASHBOARD_SECRET_KEY=<python -c "import secrets;print(secrets.token_hex(32))">
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=<werkzeug generate_password_hash output>   # REQUIRED or startup aborts
VIEWER_USERNAME=viewer
VIEWER_PASSWORD_HASH=                     # empty disables viewer login
DASHBOARD_CORS_ORIGINS=https://analytics.unilag.edu.ng
DATABASE_URL=postgresql://uraas_user:STRONG_PW@localhost:5432/uraas_db
OPENALEX_MAILTO=library@unilag.edu.ng     # identifies UNILAG traffic to aggregators
STORAGE_PATH=/opt/uraas/storage
```
Start once: if a secret is weak/missing in production, `Config.validate()` aborts by design.

### Phase D — Database
```bash
python scripts/init_db.py        # create schema (seeds UNILAG faculties/departments)
```
Use PostgreSQL in prod (the `postgres://`→`postgresql://` rewrite is automatic). Schedule
`pg_dump` backups and rehearse a restore before go-live.

### Phase E — Gunicorn + systemd (bind to localhost)
The app uses `async_mode="threading"` ⇒ worker class **`gthread`** (`gunicorn_config.py`).
**Do not** switch to eventlet/gevent without changing `async_mode`, or WebSockets break.
```ini
[Service]
User=uraas
WorkingDirectory=/opt/uraas
EnvironmentFile=/opt/uraas/.env
ExecStart=/opt/uraas/venv/bin/gunicorn -c gunicorn_config.py uraas.dashboard.app:app
Restart=always
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/uraas/storage
PrivateTmp=true
```
Set Gunicorn's `bind`/`PORT` to `127.0.0.1:8080` so only nginx can reach it.

### Phase F — nginx (TLS + reverse proxy)
`nginx/nginx.conf` already provides HTTP→HTTPS, TLS 1.2/1.3, HSTS, the `/socket.io/`
upgrade location, and `limit_req` on `/login`. Update `server_name` to
`analytics.unilag.edu.ng` (it currently reads `repository.unilag.edu.ng`), install a TLS
cert (Certbot or UNILAG-issued), point `upstream` at the Gunicorn bind, then
`nginx -t && systemctl reload nginx`.

### Phase G — Smoke test & sign-off
- `GET /health` → 200.
- Anonymous request to a control/PII route → 401 / login redirect.
- Viewer cannot download a non-OA PDF → 403.
- Start a small crawl from the dashboard (admin); confirm the live WebSocket log streams and
  papers land in the DB. Confirm in the crawler logs that **only aggregator hosts** are
  contacted — never `ir.unilag.edu.ng`.
- Run CI security tooling (`bandit`, `pip-audit` per `.github/workflows/ci-cd.yml`) +
  `pytest`. Hand IT the vuln-scan/pen-test results.

---

## 6. What UNILAG IT provides / approves (Level 0)

| Item | Who |
|---|---|
| DMZ VM (2 vCPU/4 GB/40 GB), separate from the IR | UNILAG ICT |
| DNS `analytics.unilag.edu.ng` + TLS cert | UNILAG ICT |
| Firewall: inbound 443 only, outbound 443 | UNILAG ICT |
| Pen-test / vuln-scan sign-off | UNILAG security |
| (Optional) link from IR UI → dashboard | Repository admin |

**Not required for Level 0:** any DSpace/IR credentials, IR admin access, internal LAN
access, IR database access, or any deployment onto the repository server. (Level 1 adds only
a coordination email to `dspace@unilag.edu.ng` for the public OAI harvest — still no creds.)

---

## 7. Rollback & blast-radius

The systems are decoupled, so removal is trivial and the IR is unaffected:
- **Stop:** `systemctl stop uraas nginx`. IR untouched (it never depended on URAAS).
- **Remove:** delete the VM/container. Nothing on the IR side changes.
- **Pause crawling only:** don't start it / disable any cron. IR sees nothing either way
  (it never saw URAAS traffic).
- **Worst case (URAAS host fully compromised):** confined to that host — no write path, no
  credentials, and no network route into the IR or internal UNILAG systems.

---

## 8. Residual items (improve URAAS; none affect IR safety)
- [x] (Level 1) Read-only OAI-PMH harvester spider — **done** (`oai_spider.py`).
- [ ] Schedule the OAI harvest (nightly incremental cron/systemd timer) once UNILAG approves.
- [ ] Migrate dev SQLite → PostgreSQL with automated, tested backups before go-live.
- [ ] Institutional SSO (Shibboleth/LDAP) to augment the interim username/password auth.
- [ ] Register a production ARK NAAN (currently the `99999` test NAAN) before citing ARKs.
- [ ] WCAG 2.1/2.2 AA accessibility audit; uptime/error monitoring + alerting.

---

## 9. Quick reference
```text
WHAT THE CRAWLER ACTUALLY HITS              THE UNILAG IR
─────────────────────────────────          ────────────────────────────
api.openalex.org   (ROR-filtered)           ir.unilag.edu.ng       ◄── NO URAAS TRAFFIC
api.crossref.org                            api-ir.unilag.edu.ng   ◄── NO URAAS TRAFFIC
arxiv.org                                    api-ir.../oai/request  ◄── Level 1: read-only
pub.orcid.org                                    OAI-PMH harvest (ListRecords only,
*.unilag.edu.ng faculty sites (polite)           protocol-incapable-of-writing) — BUILT
        │
        ▼ stored in URAAS's OWN local DB + PDFs on the URAAS host
```
**Contacts:** URAAS/library — `library@unilag.edu.ng`; (Level 1) repository OAI —
`dspace@unilag.edu.ng`.
