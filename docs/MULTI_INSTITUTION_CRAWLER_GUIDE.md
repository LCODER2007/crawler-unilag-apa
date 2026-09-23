# Multi-Institution Crawler Guide

**Version**: 1.0
**Date**: May 1, 2026
**Status**: Production Ready

---

## Quick Start

### Basic Usage

```bash
# Crawl UNILAG using OpenAlex (default)
python crawl_multi_institution.py --institutions unilag --target 50

# Crawl multiple institutions
python crawl_multi_institution.py --institutions unilag,ui,oau --target 100 --spider openalex

# Use different spider
python crawl_multi_institution.py --institutions ui --target 50 --spider crossref
```

---

## Available Institutions

| Short Name | Full Name | ROR ID | Staff Count |
|------------|-----------|--------|-------------|
| `unilag` | University of Lagos | 03qcnxw14 | 954 |
| `ui` | University of Ibadan | 01js2sh04 | 300 |
| `oau` | Obafemi Awolowo University | 03yp73w09 | 302 |
| `unn` | University of Nigeria, Nsukka | 00w5h6x08 | 300 |
| `abu` | Ahmadu Bello University | 00qgqjq02 | 300 |

---

## Available Spiders

### 1. OpenAlex (Recommended)
**Best for**: Comprehensive coverage, reliable metadata

```bash
python crawl_multi_institution.py --institutions unilag,ui --target 100 --spider openalex
```

**Features**:
- ROR-based querying
- Cursor pagination (exhaustive)
- Open access PDF links
- Author ORCID IDs
- Comprehensive metadata

**Rate Limit**: 1 second delay
**Expected Speed**: ~50 papers/minute

---

### 2. Crossref
**Best for**: DOI-based papers, journal articles

```bash
python crawl_multi_institution.py --institutions ui,oau --target 50 --spider crossref
```

**Features**:
- Affiliation-based search
- DOI for all papers
- Journal metadata
- Author information

**Rate Limit**: 1 second delay
**Expected Speed**: ~30 papers/minute

---

### 3. ArXiv
**Best for**: Preprints, physics, computer science

```bash
python crawl_multi_institution.py --institutions unilag --target 30 --spider arxiv
```

**Features**:
- Advanced search
- Full-text PDFs
- Preprint metadata
- Subject categories

**Rate Limit**: None
**Expected Speed**: ~20 papers/minute

---

### 4. Scholar
**Best for**: Broad coverage, citation data

```bash
python crawl_multi_institution.py --institutions ui --target 20 --spider scholar
```

**Features**:
- Staff-targeted search
- Citation counts
- Broad coverage
- Proxy rotation

**Rate Limit**: 5 second delay (strict)
**Expected Speed**: ~5 papers/minute
**Note**: Use sparingly to avoid IP blocks

---

### 5. ORCID
**Best for**: Verified author papers, accurate attribution

```bash
python crawl_multi_institution.py --institutions unilag --target 50 --spider orcid
```

**Features**:
- ORCID-based harvesting
- Verified authorship
- Publication metadata
- Journal information

**Rate Limit**: 2 second delay
**Expected Speed**: ~10 papers/minute
**Note**: Requires ORCID cache file (e.g., `data/unilag_orcids.json`)

---

## Command-Line Options

### Required Options

- `--institutions`: Comma-separated list of institution short names
  - Example: `unilag,ui,oau`
  - Default: `unilag`

### Optional Options

- `--target`: Target number of papers per institution
  - Example: `100`
  - Default: `10`

- `--spider`: Spider to use for crawling
  - Choices: `openalex`, `crossref`, `arxiv`, `scholar`, `orcid`
  - Default: `openalex`

---

## Usage Examples

### Example 1: Quick Test Crawl
```bash
# Test with 10 papers from UNILAG using OpenAlex
python crawl_multi_institution.py --institutions unilag --target 10
```

### Example 2: Multi-Institution Comparison
```bash
# Crawl 100 papers from UNILAG and UI for comparison
python crawl_multi_institution.py --institutions unilag,ui --target 100 --spider openalex
```

### Example 3: Comprehensive Crawl
```bash
# Crawl all 5 institutions with 200 papers each
python crawl_multi_institution.py --institutions unilag,ui,oau,unn,abu --target 200 --spider openalex
```

### Example 4: Specific Domain Focus
```bash
# Use ArXiv for STEM papers
python crawl_multi_institution.py --institutions unilag,ui --target 50 --spider arxiv
```

### Example 5: High-Quality Metadata
```bash
# Use Crossref for DOI-based papers
python crawl_multi_institution.py --institutions ui,oau,unn --target 100 --spider crossref
```

---

## Output and Storage

### Database Storage

All crawled papers are stored in `uraas.db` with:
- `institution_ror`: ROR ID of the institution
- `institution`: Full institution name
- All standard paper metadata

### Verification

Check crawled papers:
```bash
# Using SQLite
sqlite3 uraas.db "SELECT institution, COUNT(*) FROM papers GROUP BY institution;"
```

Expected output:
```
University of Lagos|988
University of Ibadan|150
Obafemi Awolowo University|120
```

---

## Pipeline Processing

Papers go through these pipelines:

1. **AffiliationFilterPipeline**
   - Validates institution affiliation
   - Checks staff membership
   - Tags with ROR ID

2. **DatabasePipeline**
   - Stores in database
   - Handles duplicates
   - Updates metadata

3. **UnpaywallPipeline** (if enabled)
   - Finds open-access PDFs
   - Downloads PDFs
   - Stores in `storage/pdfs/`

---

## Monitoring and Logs

### Real-Time Monitoring

Watch the crawl progress:
```bash
# Scrapy logs show:
# - Papers found per institution
# - Validation results
# - Database insertions
# - Errors and warnings
```

### Log Levels

- `INFO`: Normal operation
- `WARNING`: Validation failures, missing data
- `ERROR`: API failures, database errors

---

## Troubleshooting

### Issue 1: Institution Not Found
```
 'xyz' not found in registry
```

**Solution**: Check institution short name. Use one of: `unilag`, `ui`, `oau`, `unn`, `abu`

### Issue 2: No Papers Found
```
Found 0 works from OpenAlex
```

**Possible Causes**:
1. Institution has no papers in the source
2. ROR ID mismatch
3. API rate limit hit

**Solution**: Try different spider or check institution configuration

### Issue 3: ORCID Spider No Cache
```
No ORCID cache found. Run find_orcids.py first.
```

**Solution**: Create ORCID cache file:
```bash
# Create data/unilag_orcids.json with format:
{
  "Prof. John Doe": "0000-0001-2345-6789",
  "Dr. Jane Smith": "0000-0002-3456-7890"
}
```

### Issue 4: Rate Limit Errors
```
429 Too Many Requests
```

**Solution**:
- Increase `DOWNLOAD_DELAY` in spider settings
- Use different spider
- Wait before retrying

---

## Best Practices

### 1. Start Small
```bash
# Test with 10 papers first
python crawl_multi_institution.py --institutions unilag --target 10
```

### 2. Use OpenAlex for Bulk
```bash
# OpenAlex is most reliable for large crawls
python crawl_multi_institution.py --institutions unilag,ui,oau --target 500 --spider openalex
```

### 3. Combine Multiple Spiders
```bash
# Run different spiders for comprehensive coverage
python crawl_multi_institution.py --institutions unilag --target 200 --spider openalex
python crawl_multi_institution.py --institutions unilag --target 100 --spider crossref
python crawl_multi_institution.py --institutions unilag --target 50 --spider arxiv
```

### 4. Monitor Database Growth
```bash
# Check paper count regularly
sqlite3 uraas.db "SELECT COUNT(*) FROM papers;"
```

### 5. Verify Data Quality
```bash
# Run validation tests
python test_multi_institution.py
```

---

## Performance Optimization

### Parallel Crawling

The crawler automatically runs institutions in parallel:
```bash
# This crawls UNILAG, UI, and OAU simultaneously
python crawl_multi_institution.py --institutions unilag,ui,oau --target 100
```

### Batch Processing

For large-scale crawling:
```bash
# Day 1: UNILAG and UI
python crawl_multi_institution.py --institutions unilag,ui --target 1000 --spider openalex

# Day 2: OAU and UNN
python crawl_multi_institution.py --institutions oau,unn --target 1000 --spider openalex

# Day 3: ABU
python crawl_multi_institution.py --institutions abu --target 1000 --spider openalex
```

### Resource Management

- **Memory**: ~500MB per spider instance
- **Disk**: ~1MB per 100 papers (without PDFs)
- **Network**: ~10MB per 100 papers

---

## Integration with Dashboard

After crawling, papers are immediately available in the dashboard:

1. **Multi-Institution Comparator**
   - Navigate to "Comparator" tab
   - Select institutions to compare
   - View side-by-side metrics

2. **Institution Analytics**
   - Filter by institution ROR
   - View institution-specific trends
   - Export institution reports

3. **Collaboration Analysis**
   - Identify cross-institution papers
   - Map collaboration networks
   - Track partnership growth

---

## Advanced Usage

### Custom Institution Configuration

Add new institution:
```bash
# Create config/institutions/new_uni.json
{
  "ror": "https://ror.org/xxxxxxxxx",
  "name": "New University",
  "short_name": "NU",
  "country": "Nigeria",
  "staff_file": "data/new_uni_staff.json",
  "affiliation_patterns": [
    "New University",
    "NU, Nigeria"
  ]
}
```

### Custom Spider Settings

Modify spider behavior:
```python
# In spider file
custom_settings = {
    'DOWNLOAD_DELAY': 2.0,  # Increase delay
    'CONCURRENT_REQUESTS': 8,  # More parallel requests
    'RETRY_TIMES': 5,  # More retries
}
```

---

## Testing

### Unit Tests
```bash
# Test institution registry
python test_multi_institution.py

# Test spider initialization
python test_multi_institution_crawl.py

# Test all spiders
python test_all_spiders.py
```

### Integration Tests
```bash
# Small crawl test
python crawl_multi_institution.py --institutions unilag --target 5 --spider openalex

# Verify in database
sqlite3 uraas.db "SELECT title, institution FROM papers LIMIT 5;"
```

---

## Support and Maintenance

### Regular Maintenance

1. **Weekly**: Verify spider functionality
2. **Monthly**: Update staff lists
3. **Quarterly**: Review institution configurations
4. **Annually**: Update ROR IDs if changed

### Health Checks

```bash
# Check institution registry
python -c "from uraas.config.institutions import get_registry; print(len(get_registry().list_all()))"

# Check staff counts
python -c "from uraas.config.institutions import get_registry; [print(f'{c.short_name}: {len(c.staff_names)}') for c in get_registry().list_all()]"
```

---

## Appendix: Spider Comparison Matrix

| Feature | OpenAlex | Crossref | ArXiv | Scholar | ORCID |
|---------|----------|----------|-------|---------|-------|
| ROR Support |  |  |  |  |  |
| DOI Coverage | High | Very High | Medium | Medium | High |
| PDF Links |  | Limited |  | Limited |  |
| Abstracts |  | Limited |  |  |  |
| Author ORCID |  |  |  |  |  |
| Citations |  |  |  |  |  |
| Speed | Fast | Medium | Medium | Slow | Medium |
| Reliability | High | High | High | Medium | High |
| Coverage | Broad | Broad | STEM | Broad | Verified |

---

**Guide Version**: 1.0
**Last Updated**: May 1, 2026
**Maintained By**: Technical Team
