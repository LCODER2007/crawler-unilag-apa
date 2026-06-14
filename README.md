# URAAS - APA Intelligence & Analytics Platform

**World-class institutional repository intelligence system for African universities.** Built for the Africa PID Alliance, this platform provides strategic research intelligence, multi-institution comparison, and indigenous knowledge tracking.

## 🎯 Core Features (APA Intelligence Platform)

### Multi-Institution Comparator Engine
- Compare 2-10 African institutions simultaneously
- Strategic metrics: TK Vitality, Linguistic Diversity, Patent Velocity
- Rankings across research volume, OA adoption, innovation commercialization
- Senate report generation (JSON, CSV, PDF)
- Collaboration mesh visualization

### Novel African-Focused Metrics
- **TK Vitality Score**: Indigenous knowledge preservation tracking
- **Linguistic Diversity Index**: African language research output measurement
- **Patent Velocity Tracker**: Innovation commercialization timeline analysis
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

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│           APA INTELLIGENCE & ANALYTICS PLATFORM             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: Data Ingestion                                   │
│  ├─ Multi-Source Crawlers (arXiv, Scholar, OpenAlex)      │
│  ├─ DocID Repository Crawler (ir.unilag.edu.ng)           │
│  ├─ Staff Validator (fuzzy name matching)                 │
│  └─ Affiliation Filter (ROR-based)                        │
│                                                             │
│  Layer 2: Intelligence Engine                              │
│  ├─ TK Vitality Score Calculator                          │
│  ├─ Linguistic Diversity Analyzer                         │
│  ├─ Patent Velocity Tracker                               │
│  ├─ Multi-Institution Comparator                          │
│  └─ Collaboration Network Builder                         │
│                                                             │
│  Layer 3: Strategic Reporting                              │
│  ├─ Senate Report Generator                               │
│  ├─ Rankings & Insights Engine                            │
│  ├─ Gap Analysis (vs peer institutions)                   │
│  └─ Recommendations Generator                             │
│                                                             │
│  Layer 4: Presentation                                     │
│  ├─ Interactive Dashboard (Flask + D3.js)                 │
│  ├─ REST API (JSON responses)                             │
│  ├─ Export Formats (CSV, BibTeX, JSON, PDF)              │
│  └─ Real-Time Updates (WebSocket)                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 📋 Prerequisites

- Python 3.9+
- PostgreSQL 15+ (or SQLite for development)
- 10GB+ free disk space for PDF storage
- Modern web browser (Chrome, Firefox, Edge)

## 🚀 Quick Start

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

## 🎛️ Dashboard Features

### Tab 1: Crawler
- Start/stop research paper mining
- Live terminal feed with WebSocket updates
- DocID™ repository crawler for institutional archives
- Recently harvested papers display

### Tab 2: Archive
- Hierarchical view: Faculty → Department → Papers
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

## 🌍 Multi-Institution Comparator

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

## 📊 Novel African-Focused Metrics

### TK Vitality Score

Measures indigenous knowledge preservation efforts.

**Formula**: Weighted sum of content types / total items × 100

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

**Formula**: African language outputs / total outputs × 100

**Supported Languages**: Yoruba, Igbo, Hausa, Swahili, Amharic, Somali, Kinyarwanda, Zulu, Xhosa, Afrikaans, and 10+ more

**Strategic Value**: Measures decolonization of knowledge production

**API Endpoint**: `GET /api/analytics/linguistic-diversity-index`

### Patent Velocity Tracker

Analyzes innovation commercialization timelines.

**Formula**: Average(Patent date - Publication date)

**Interpretation**:
- < 1 year: Fast movers (rapid innovation)
- 1-2 years: Standard pipeline
- 2-5 years: Slow (opportunity for improvement)
- > 5 years: Very slow (IP management issues)

**API Endpoint**: `GET /api/analytics/patent-velocity`

### DocID Coverage

Tracks Africa PID Alliance identifier adoption.

**Formula**: Papers with DocID / total papers × 100

**API Endpoint**: `GET /api/analytics/docid-coverage`

## 🔌 API Endpoints

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

### Search Endpoints

```bash
# Advanced search with Boolean operators
GET /api/search/advanced?q="machine learning" AND author:smith&sort=date&limit=50

# Simple search
GET /api/analytics/search?q=covid&faculty=science&year_from=2020&oa_only=true
```

## 📁 Project Structure

```
uraas/
├── analytics/
│   └── engine.py              # TK Vitality, Linguistic Diversity, Patent Velocity
├── dashboard/
│   ├── app.py                 # Flask app with comparator endpoints
│   ├── templates/
│   │   └── index.html         # Main dashboard (with comparator tab)
│   └── static/
│       └── css/
│           └── professional.css  # Design system
├── services/
│   ├── comparator_engine.py   # Multi-institution comparison
│   ├── citation_tracker.py    # Citation tracking & h-index
│   └── advanced_search.py     # Boolean search engine
├── spiders/
│   └── sources/
│       ├── arxiv_spider.py
│       ├── scholar_spider.py
│       ├── openalex_spider.py
│       ├── crossref_spider.py
│       ├── orcid_spider.py
│       └── faculty_directory_spider.py
├── pipelines/
│   ├── affiliation_filter.py  # Staff validation
│   ├── unpaywall.py           # OA status enrichment
│   ├── gap_analysis.py        # Deduplication
│   └── database.py            # Storage with ROR support
├── utils/
│   ├── unilag_classifier.py   # Faculty/dept classification
│   ├── staff_validator.py     # Staff name validation
│   ├── pdf_downloader.py      # PDF download & storage
│   ├── docid_generator.py     # Africa PID Alliance DocID
│   └── normalizer.py          # Text normalization
├── config.py                   # Configuration
└── database.py                 # SQLAlchemy models (with ROR)

data/
├── unilag_staff.json           # 946 staff names
└── staff_department_map.json  # Department mappings

storage/
└── pdfs/                       # 127 downloaded PDFs
```

## 🗄️ Database Schema

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

## 🎓 Adding More Institutions

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

## 🚀 Deployment

### Development

```bash
python start_dashboard.py
```

### Production (Render.com)

```bash
# Uses gunicorn with production config
gunicorn -c gunicorn_config.py uraas.dashboard.app:app
```

Configuration in `gunicorn_config.py`:
- 4 workers
- 120s timeout
- Access logging
- Error logging

### Docker

```bash
docker-compose up -d
```

## 🔐 Security Notes

- Dashboard has NO authentication by default (add OAuth before production)
- PDFs are stored locally (ensure adequate disk space)
- Rate limiting enabled (2s delay between requests)
- Respect publisher copyright (Unpaywall integration helps)

## 📈 Roadmap

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

## 🎯 UNESCO Presentation Readiness

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

## 📝 License

Licensed under the **Apache License 2.0** — see [LICENSE](LICENSE).

## 🔒 Privacy & Data Protection

URAAS processes already-published scholarly metadata in line with the Nigeria Data Protection Act
2023. See the [Privacy Notice](PRIVACY_NOTICE.md) for the lawful basis, data handled, and how
researchers can request access, correction, or removal of their data.

## 🤝 Contributing

[Add contribution guidelines]

## 📧 Contact

For issues or questions, contact: library@unilag.edu.ng

---

**Built with ❤️ for the Africa PID Alliance and UNESCO**

**Status**: Core platform implemented and functional. Comparator integrated. Ready for internal testing and stakeholder review.
