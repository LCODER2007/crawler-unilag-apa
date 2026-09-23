# URAAS - APA Intelligence & Analytics Platform

**World-class institutional repository intelligence system for African universities.** Built for the Africa PID Alliance, this platform provides strategic research intelligence, multi-institution comparison, and indigenous knowledge tracking.

## Core Features (APA Intelligence Platform)

### Multi-Institution Comparator Engine
- Compare 2-10 African institutions simultaneously
- Strategic metrics: TK Vitality, Linguistic Diversity (Patent Velocity: roadmap, see below)
- Rankings across research volume, OA adoption, innovation commercialization
- Senate report generation (JSON, CSV, PDF)
- Collaboration mesh visualization

### Novel African-Focused Metrics
- **TK Vitality Score**: Indigenous knowledge preservation tracking
- **Linguistic Diversity Index**: African language research output measurement
- **Patent Velocity Tracker**:  Roadmap - no patent data source integrated yet
- **DocID Coverage**: Africa PID Alliance identifier adoption rate

### Research Intelligence
- Staff-validated harvesting (946 UNILAG staff members)
- Multi-source discovery (arXiv, Scholar, OpenAlex, Crossref, ORCID)
- Intelligent deduplication (DOI, URL, fuzzy title matching)
- Local PDF storage with SHA256 verification
- Smart access control via Unpaywall integration

### Real-Time Dashboard
- Live crawler monitoring with WebSocket updates
- Multi-institution comparison interface
- Interactive analytics with D3.js visualizations
- Faculty/department hierarchical navigation
- Advanced Boolean search (Scopus-style operators)

## Architecture

```
+-------------------------------------------------------------+
|           APA INTELLIGENCE & ANALYTICS PLATFORM             |
+-------------------------------------------------------------+
|                                                             |
|  Layer 1: Data Ingestion                                   |
|  +- Multi-Source Crawlers (arXiv, Scholar, OpenAlex)      |
|  +- DocID Repository Crawler (ir.unilag.edu.ng)           |
|  +- Staff Validator (fuzzy name matching)                 |
|  +- Affiliation Filter (ROR-based)                        |
|                                                             |
|  Layer 2: Intelligence Engine                              |
|  +- TK Vitality Score Calculator                          |
|  +- Linguistic Diversity Analyzer                         |
|  +- Patent Velocity Tracker                               |
|  +- Multi-Institution Comparator                          |
|  +- Collaboration Network Builder                         |
|                                                             |
|  Layer 3: Strategic Reporting                              |
|  +- Senate Report Generator                               |
|  +- Rankings & Insights Engine                            |
|  +- Gap Analysis (vs peer institutions)                   |
|  +- Recommendations Generator                             |
|                                                             |
|  Layer 4: Presentation                                     |
|  +- Interactive Dashboard (Flask + D3.js)                 |
|  +- REST API (JSON responses)                             |
|  +- Export Formats (CSV, BibTeX, JSON, PDF)              |
|  +- Real-Time Updates (WebSocket)                         |
|                                                             |
+-------------------------------------------------------------+
```

## Prerequisites

- Python 3.9+
- PostgreSQL 15+ (or SQLite for development)
- 10GB+ free disk space for PDF storage
- Modern web browser (Chrome, Firefox, Edge)

## Quick Start

### 1. Clone and Setup

```bash
git clone <repository-url>
cd uraas
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Initialize Database

```bash
python init_db.py
```

This creates all tables, seeds UNILAG's 12 faculties and 80+ departments, and prepares the ROR-based multi-institution schema.

### 3. Start the Dashboard

```bash
python start_dashboard.py
```

Open http://localhost:8080 in your browser.

### 4. Navigate to Comparator Tab

Press **5** or click the **Comparator** tab to access the Multi-Institution Comparison Engine.

## Dashboard Features

### Tab 1: Crawler
- Start/stop research paper mining
- Live terminal feed with WebSocket updates
- DocID™ repository crawler for institutional archives
- Recently harvested papers display

### Tab 2: Archive
- Hierarchical view: Faculty -> Department -> Papers
- 988 UNILAG papers indexed
- CSV and BibTeX export
- Full-text search

### Tab 3: Search
- Advanced Boolean operators (AND, OR, NOT)
- Field-specific queries (author:, year:, faculty:, doi:)
- Phrase matching with quotes
- Open Access filtering

### Tab 4: Analytics
- Publications by year/faculty
- Top authors ranking
- SDG alignment analysis
- Research trends tracking
- Collaboration networks
- Language research identification

### Tab 5: Comparator (NEW - APA Core Feature)
- Multi-institution comparison (2-10 institutions)
- Strategic metrics dashboard
- Rankings across all dimensions
- Senate report generation
- Collaboration mesh visualization
- Strategic insights & recommendations

## Multi-Institution Comparator

### How to Use

1. Navigate to **Comparator** tab (press 5)
2. Add institutions by ROR ID or use quick-add dropdown
3. Click **Run Comparison**
4. View results:
   - Executive summary cards
   - Detailed comparison matrix
   - Rankings (volume, OA, TK, patents)
   - Strategic insights
   - Collaboration network

### Comparison Metrics

For each institution:
- **Total Papers**: Research volume
- **Total Authors**: Unique researchers
- **OA Rate**: Open access adoption percentage
- **TK Rate**: Indigenous knowledge preservation percentage
- **Patent Rate**: Innovation commercialization percentage
- **African Language Rate**: Linguistic diversity percentage
- **Growth Rate**: 3-year publication growth
- **Papers per Author**: Productivity ratio
- **Patents per 100 Papers**: Innovation efficiency
- **DocID Coverage**: PID adoption rate

### Senate Report

Generate comprehensive reports for university leadership:
- Executive summary
- Detailed comparison matrix
- Rankings across all metrics
- Strategic insights
- Recommendations
- Collaboration network data

**Export Formats**: JSON (implemented), CSV (TODO), PDF (TODO)

## Novel African-Focused Metrics

### TK Vitality Score

Measures indigenous knowledge preservation efforts.

**Formula**: Weighted sum of content types / total items x 100

**Content Type Weights**:
- Indigenous Knowledge: 3.0
- Cultural Heritage: 2.5
- Oral Tradition: 2.5
- Grey Literature: 1.5
- Thesis: 1.2
- Dataset: 1.2
- Patent: 1.0
- Research Paper: 0.5

**Interpretation**:
- 60-100: Excellent cultural preservation
- 30-59: Good indigenous knowledge focus
- 0-29: Opportunity for growth

**API Endpoint**: `GET /api/analytics/tk-vitality-score`

### Linguistic Diversity Index

Tracks research outputs in African languages.

**Formula**: African language outputs / total outputs x 100

**Supported Languages**: Yoruba, Igbo, Hausa, Swahili, Amharic, Somali, Kinyarwanda, Zulu, Xhosa, Afrikaans, and 10+ more

**Strategic Value**: Measures decolonization of knowledge production

**API Endpoint**: `GET /api/analytics/linguistic-diversity-index`

### Patent Velocity Tracker -  Roadmap, not implemented

Would analyze innovation commercialization timelines (patent date − publication date), but
**no patent data source is integrated anywhere in this codebase.** `Item.patent_id`/`patent_date`
exist as schema columns with no spider, API client, or backfill script that ever populates them.
The comparator's `patent_rate` metric reports this honestly as "no data" rather than a fabricated
0%. There is no `/api/analytics/patent-velocity` endpoint - that line below was aspirational, not
built.

### DocID Coverage

Tracks Africa PID Alliance identifier adoption.

**Formula**: Papers with DocID / total papers x 100

**API Endpoint**: `GET /api/analytics/docid-coverage`

## API Endpoints

### Comparator Endpoints

```bash
# Compare institutions
POST /api/comparator/compare
Body: {"ror_ids": ["https://ror.org/03qcnxw14", "https://ror.org/01js2sh04"]}

# Get collaboration network
POST /api/comparator/collaboration-mesh
Body: {"ror_ids": ["ror1", "ror2"]}

# Generate senate report
POST /api/comparator/senate-report
Body: {"ror_ids": ["ror1", "ror2"], "format": "json"}
```

### Analytics Endpoints

```bash
# TK Vitality Score
GET /api/analytics/tk-vitality-score

# Linguistic Diversity Index
GET /api/analytics/linguistic-diversity-index

# Patent Velocity
GET /api/analytics/patent-velocity

# DocID Coverage
GET /api/analytics/docid-coverage

# Overview stats
GET /api/analytics/overview

# Publications by year
GET /api/analytics/publications-by-year

# Top authors
GET /api/analytics/top-authors?limit=20
```

### Keyword Endpoints

```bash
# Keywords for one record (extracted and persisted on first read if absent)
GET /api/keywords/<id>

# Records sharing the most keywords with this one
GET /api/keywords/<id>/related?limit=10

# Records carrying a keyword
GET /api/keywords/search?q=indigenous%20knowledge&sc_only=1

# Corpus-level TF-IDF keyword cloud
GET /api/analytics/keyword-cloud?top_n=60

# How much of the corpus has keywords at all
GET /api/keywords/coverage

# Fill in missing keywords (admin)
POST /api/admin/keywords/backfill   { "limit": 500 }
```

### Citation Endpoints

```bash
# Counts, ARK, DOCiD and Pan-African citation share for one record
GET /api/citations/<id>

# The citation edge list, both directions
GET /api/citations/<id>/graph?limit=200

# How much of the corpus has a stored graph
GET /api/citations/coverage

# Fetch and store a record's graph from OpenAlex (admin)
POST /api/admin/citations/sync-graph/<id>

# Bulk graph sync, runs in the background (admin)
POST /api/admin/citations/sync-graph   { "limit": 50, "sc_only": true }
```

Edges point mostly outside the corpus, so each carries its own DOI and
OpenAlex id; `internal_id` is set only when URAAS also holds that work.
Inbound edges are capped at 200 per record, so `edges_stored` is not
`citation_count`.

### Search Endpoints

```bash
# Advanced search with Boolean operators
GET /api/search/advanced?q="machine learning" AND author:smith&sort=date&limit=50

# Simple search
GET /api/analytics/search?q=covid&faculty=science&year_from=2020&oa_only=true
```

## Project Structure

```
uraas/                          # The application package
+-- analytics/
|   +-- engine.py               # TK Vitality, Linguistic Diversity, keyword cloud
+-- dashboard/
|   +-- app.py                  # Flask app: every HTTP endpoint
|   +-- auth.py                 # Session and API-key gate, endpoint allowlists
|   +-- responses.py            # Shared JSON and CSV response helpers
|   +-- templates/index.html    # The dashboard itself
|   +-- static/                 # css/, js/
+-- services/
|   +-- sc_engine.py            # Special Collections decision engine (SC_FILTER)
|   +-- comparator_engine.py    # Multi-institution comparison
|   +-- alignment_engine.py     # SDG / AU Agenda 2063 / UNESCO alignment
|   +-- citation_tracker.py     # Citation counts, edge list, h-index
|   +-- keyword_service.py      # Per-record keywords, backfill, related records
|   +-- advanced_search.py      # Boolean search engine
|   +-- docid_client.py         # Africa PID Alliance DOCiD client
|   +-- ir_client.py            # DSpace REST client for the UNILAG IR
|   +-- narratives.py           # Generated prose for the analytics views
|   +-- batch_approval.py       # Deposit batch review
|   +-- email_service.py        # Notification mail
+-- spiders/sources/            # 15 source spiders (OpenAlex, Crossref, OAI-PMH, ...)
+-- pipelines/
|   +-- affiliation_filter.py   # Staff validation
|   +-- unpaywall.py            # Open-access status enrichment
|   +-- gap_analysis.py         # Deduplication
|   +-- database.py             # Storage with ROR support
+-- utils/                      # Classifiers, PDF handling, DOCiD generation
+-- config/                     # Taxonomies and framework definitions
+-- config.py                   # Runtime configuration
+-- database.py                 # SQLAlchemy models and schema self-healing

deploy/                         # Everything about running it somewhere
+-- hf/                         # The live Hugging Face Space (Dockerfile, start.sh)
+-- k8s/, nginx/                # Reference configurations, not currently in use
+-- docker-compose*.yml
+-- gunicorn_config.py
+-- render.yaml

scripts/                        # Operational entry points (init_db, migrations,
|                               # backfills, push_to_hf.py, manage_api_keys.py)
docs/                           # Partner API, deployment and policy documents
tests/                          # pytest suite
```

Not in version control, created at runtime or held locally: `storage/`
(downloaded PDFs), `data/` (staff rosters, which carry personal data),
`scratch/` (local working files), `.env`, and the SQLite database. On the
live Space all of these live on the `/data` persistent volume instead.

## Database Schema

### Multi-Institution Support

All papers are tagged with ROR (Research Organization Registry) identifiers:

```sql
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    title VARCHAR(512),
    abstract TEXT,
    doi VARCHAR(255),

    -- Multi-institution support
    ror VARCHAR(128),           -- Institution ROR ID
    institution VARCHAR(255),   -- Institution name

    -- APA-specific fields
    content_type VARCHAR(50),   -- For TK Vitality
    tk_label VARCHAR(100),      -- Traditional Knowledge label
    patent_id VARCHAR(128),     -- For Patent Velocity
    patent_date DATETIME,
    language_code VARCHAR(10),  -- For Linguistic Diversity
    is_african_language BOOLEAN,
    docid VARCHAR(128),         -- Africa PID Alliance DocID

    -- Standard fields
    publication_date DATETIME,
    created_at DATETIME,
    ...
);

CREATE INDEX ix_items_ror ON items(ror);
```

### Current Data

- **988 papers** from University of Lagos
- All papers tagged with UNILAG ROR: `https://ror.org/03qcnxw14`
- **127 PDFs** stored locally
- **12 faculties**, **80+ departments**
- **946 validated staff members**

## Adding More Institutions

### Method 1: Manual Data Entry

```python
from uraas.database import SessionLocal, Item

session = SessionLocal()

paper = Item(
    title="Sample Paper",
    ror="https://ror.org/01js2sh04",  # University of Ibadan
    institution="University of Ibadan",
    # ... other fields
)
session.add(paper)
session.commit()
```

### Method 2: Crawler Extension

Modify existing crawlers to accept ROR parameter and tag papers accordingly.

### Method 3: Bulk Import

Create CSV with ROR column and import using migration script.

## Deployment

### Development

```bash
python start_dashboard.py
```

### Live instance (Hugging Face Spaces)

The live deployment is a Docker Space built from `deploy/hf/`. Deploying is a
deliberate manual step, not something CI triggers:

```bash
HF_TOKEN=hf_... python scripts/push_to_hf.py
```

The script stages a clean copy of the repo, excluding secrets, the database,
crawled PDFs and local working files, promotes `deploy/hf/Dockerfile` and
`deploy/hf/README.md` to the Space root, and uploads it. The Space rebuilds in
roughly five minutes. Runtime configuration lives in the Space's own Variables
and Secrets, never in this repo.

Live app: https://lordkiki-apa-uraas.hf.space

The Space sleeps when idle, so the first request after a quiet period takes
about 30 seconds while the container wakes.

### Other targets

`deploy/` also holds reference configurations that are not currently in use:
Docker Compose, Kubernetes (`deploy/k8s/`), nginx (`deploy/nginx/`) and Render
(`deploy/render.yaml`). Compose builds from the repo-root `Dockerfile`:

```bash
docker compose -f deploy/docker-compose.prod.yml up -d
```

Gunicorn settings for those targets are in `deploy/gunicorn_config.py`:
gthread workers to match the dashboard's SocketIO threading mode, 2 workers by
default (`GUNICORN_WORKERS` overrides), 120s timeout, access and error logs to
stdout and stderr.

## Security Notes

- Two authentication paths, both enforced by a `before_request` hook with
  explicit public, admin and partner endpoint allowlists: session cookies for
  human users, and `X-API-Key` for partner integrations
- Secrets come from the environment. `.env` is git-ignored; `.env.example`
  documents every variable without carrying a value
- Crawled PDFs stay out of version control (`storage/` is ignored) and out of
  the deployed image
- Rate limiting enabled (2s delay between requests)
- Respect publisher copyright (Unpaywall integration helps)

## Roadmap

### High Priority
- [ ] Collaboration Mesh D3.js visualization (geographic map)
- [ ] PDF report generation (ReportLab/WeasyPrint)
- [ ] OAuth authentication (ORCID integration)
- [ ] Multi-language interface (French, Portuguese, Arabic, Swahili)

### Medium Priority
- [ ] Real-time data pipeline (async ingestion)
- [ ] Elasticsearch integration for hot storage
- [ ] Advanced visualizations (Tremor charts)
- [ ] Mobile optimization

### Low Priority
- [ ] API documentation (Swagger/OpenAPI)
- [ ] Performance optimization (Redis caching)
- [ ] Lazy loading for large datasets

## UNESCO Presentation Readiness

### Key Strengths

1. **Novel Metrics**: TK Vitality, Linguistic Diversity, Patent Velocity - metrics that don't exist in Western platforms
2. **Multi-Institution Comparison**: Built from ground up for comparative analysis
3. **African Focus**: Indigenous knowledge, African languages, cultural preservation
4. **Strategic Intelligence**: Decision-making tool for VCs and research leaders
5. **Data Sovereignty**: Read-only DocID integration, African-owned infrastructure

### Demo Flow

1. Show UNILAG dashboard with 988 papers
2. Navigate to Comparator tab (press 5)
3. Add 2-3 institutions
4. Run comparison showing metrics
5. Generate senate report
6. Highlight TK Vitality Score
7. Show Linguistic Diversity Index
8. Demonstrate Patent Velocity tracking

### Key Messages

- "Observer Engine" architecture - non-intrusive intelligence layer
- Empowers African research leadership with data-driven decisions
- Answers questions VCs actually ask
- Built for Africa, by Africa
- Complements DocID infrastructure without modifying it

## License

Licensed under the **Apache License 2.0** - see [LICENSE](LICENSE).

## Privacy & Data Protection

URAAS processes already-published scholarly metadata in line with the Nigeria Data Protection Act
2023. See the [Privacy Notice](PRIVACY_NOTICE.md) for the lawful basis, data handled, and how
researchers can request access, correction, or removal of their data.

## Contributing

[Add contribution guidelines]

## Contact

For issues or questions, contact: library@unilag.edu.ng

---

**Built with  for the Africa PID Alliance and UNESCO**

**Status**: Core platform implemented and functional. Comparator integrated. Ready for internal testing and stakeholder review.
