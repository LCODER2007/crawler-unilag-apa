# APA Intelligence & Analytics Platform
## Technical Implementation Report and Collaborative Workplan

**Project Duration**: March 25, 2026 - April 25, 2026 (1 Month)
**Collaborating Institutions**:
- University of Lagos (UNILAG) - Technical Team
- TCC Africa / Africa PID Alliance DocID Team - Technical Team

**Document Version**: 1.0
**Date**: April 25, 2026
**Status**: Phase 1 Complete - Transition to Collaborative Development

---

## Executive Summary

This document outlines the technical work completed during the initial development phase of the APA Intelligence & Analytics Platform and establishes a structured workplan for collaborative development between UNILAG's technical team and TCC Africa's DocID technical team over the next month.

The platform has successfully transitioned from a single-institution repository system to a multi-institution intelligence platform capable of comparative analysis across African universities. Core infrastructure is operational with 988 papers indexed, ROR-based multi-tenancy implemented, and novel African-focused metrics deployed.

---

## Section 1: Work Completed (March 25 - April 25, 2026)

### 1.1 Infrastructure Development

#### Database Architecture
- Migrated from single-institution to multi-institution schema
- Implemented ROR (Research Organization Registry) identifier support
- Added 988 UNILAG papers with ROR tagging (https://ror.org/03qcnxw14)
- Created indexes for efficient multi-institution queries
- Established Dublin Core metadata compliance

**Technical Specifications**:
- Database: SQLite (development) / PostgreSQL-ready (production)
- ORM: SQLAlchemy 2.0
- Migration system: Custom Python scripts
- Current dataset: 988 papers, 127 PDFs, 946 validated staff members

#### Multi-Source Data Ingestion
- Implemented 6 data source spiders:
  - arXiv API integration
  - Google Scholar crawler with proxy rotation
  - OpenAlex ROR-based queries
  - Crossref REST API
  - ORCID public API
  - UNILAG faculty directory scraper

- Staff validation system with fuzzy name matching (85% threshold)
- Affiliation filtering using institutional patterns
- Deduplication pipeline (DOI, URL, fuzzy title matching at 95% threshold)

### 1.2 Novel African-Focused Metrics

#### TK Vitality Score
Measures indigenous knowledge preservation efforts through weighted content type analysis.

**Implementation**:
- Content type classification system
- Weighted scoring algorithm (Indigenous Knowledge: 3.0, Cultural Heritage: 2.5, etc.)
- Temporal tracking of TK preservation trends
- API endpoint: `/api/analytics/tk-vitality-score`

**Current UNILAG Score**: Baseline established, tracking initiated

#### Linguistic Diversity Index
Tracks research outputs in African languages to measure knowledge decolonization.

**Implementation**:
- Language detection for 20+ African languages
- Yoruba, Igbo, Hausa, Swahili, Amharic, Zulu, Xhosa support
- Percentage calculation against total output
- API endpoint: `/api/analytics/linguistic-diversity-index`

**Current UNILAG Index**: Baseline established

#### Patent Velocity Tracker
Analyzes innovation commercialization timelines from publication to patent.

**Implementation**:
- Patent ID tracking in database schema
- Timeline calculation (patent date - publication date)
- Fast mover identification (under 1 year)
- Statistical analysis of commercialization patterns
- API endpoint: `/api/analytics/patent-velocity`

**Current UNILAG Data**: Patent tracking infrastructure ready

#### DocID Coverage Metric
Tracks Africa PID Alliance identifier adoption rates.

**Implementation**:
- DocID field in database schema
- Coverage percentage calculation
- Institutional repository crawler for DocID assignment
- API endpoint: `/api/analytics/docid-coverage`

**Current UNILAG Coverage**: Infrastructure ready for DocID integration

### 1.3 Multi-Institution Comparator Engine

#### Core Functionality
- Simultaneous comparison of 2-10 institutions
- ROR-based institution identification
- Comprehensive metric calculation per institution
- Ranking system across 8 key dimensions
- Strategic insights generation
- Gap analysis and recommendations

**Implemented Metrics**:
- Total papers and authors
- Open access adoption rate
- Indigenous knowledge preservation rate
- Patent commercialization rate
- African language output rate
- 3-year growth trajectory
- Productivity ratios (papers per author)
- Innovation efficiency (patents per 100 papers)

**API Endpoints**:
- `POST /api/comparator/compare` - Run multi-institution comparison
- `POST /api/comparator/collaboration-mesh` - Generate collaboration network
- `POST /api/comparator/senate-report` - Generate executive reports

#### Senate Report Generator
- JSON format implemented and operational
- Executive summary generation
- Detailed comparison matrices
- Rankings across all metrics
- Strategic recommendations
- Collaboration network data

**Pending Formats**: CSV export, PDF generation with charts

### 1.4 User Interface Development

#### Dashboard Implementation
- Five-tab navigation system:
  1. Crawler - Data ingestion control
  2. Archive - Hierarchical paper browsing
  3. Search - Advanced Boolean search
  4. Analytics - Visualization and trends
  5. Comparator - Multi-institution comparison (NEW)

- Real-time updates via WebSocket
- Responsive design with dark/light theme
- Professional CSS design system
- Keyboard shortcuts for navigation

#### Comparator Interface
- Institution selection (ROR ID or name)
- Quick-add dropdown for major African universities
- Executive summary cards
- Detailed comparison table
- Rankings visualization
- Strategic insights display
- Collaboration mesh placeholder (visualization pending)

### 1.5 API Development

#### REST API Endpoints
Total endpoints implemented: 45+

**Categories**:
- Paper management (8 endpoints)
- Analytics (15 endpoints)
- Search (3 endpoints)
- Comparator (3 endpoints)
- Export (2 endpoints)
- Crawler control (6 endpoints)
- DocID operations (2 endpoints)

**Authentication**: None (development phase)
**Rate Limiting**: 2-second delay between requests
**Response Format**: JSON

### 1.6 Data Quality and Validation

#### Staff Validation System
- 946 UNILAG staff members validated
- Fuzzy name matching with Levenshtein distance
- Affiliation cross-checking
- Email domain verification (@unilag.edu.ng)
- Manual override capability

#### Deduplication Pipeline
- DOI exact matching
- URL exact matching
- Fuzzy title matching (95% threshold)
- Cross-source duplicate detection
- Merge conflict resolution

#### PDF Management
- 127 PDFs downloaded and stored
- SHA256 hash verification
- Access policy enforcement (Unpaywall integration)
- Local storage with organized naming
- Download API endpoint

### 1.7 Classification System

#### Faculty and Department Mapping
- 12 UNILAG faculties configured
- 80+ departments mapped
- Keyword-based automatic classification
- Manual override capability
- Hierarchical navigation in UI

**Faculties**:
- Faculty of Arts
- Faculty of Science
- Faculty of Engineering
- College of Medicine
- Faculty of Pharmacy
- Faculty of Dental Sciences
- Faculty of Basic Medical Sciences
- Faculty of Social Sciences
- Faculty of Law
- Faculty of Education
- Faculty of Environmental Sciences
- Faculty of Management Sciences

---

## Section 2: Technical Gaps and Limitations

### 2.1 Current Limitations

#### Data Coverage
- Single institution fully indexed (UNILAG only)
- Limited multi-institution comparison capability without additional data
- Patent data sparse (infrastructure ready, data collection needed)
- TK labels not systematically applied to existing papers
- African language detection needs manual verification

#### Visualization
- Collaboration mesh visualization not implemented (D3.js integration pending)
- Geographic map visualization absent
- Interactive charts limited to Chart.js basics
- No export to image formats (PNG, SVG)

#### Authentication and Security
- No user authentication system
- No role-based access control
- No institutional access restrictions
- API endpoints publicly accessible
- No audit logging

#### DocID Integration
- Read-only integration not yet established with TCC Africa infrastructure
- DocID assignment logic implemented but not connected to official registry
- No bidirectional synchronization
- Coverage tracking ready but not operational

#### Report Generation
- Senate reports only in JSON format
- PDF generation not implemented
- No chart embedding in reports
- No institutional branding in exports
- Limited customization options

### 2.2 Performance Considerations

#### Scalability Concerns
- SQLite suitable for development only
- No caching layer (Redis recommended)
- No query optimization for large datasets
- Synchronous processing (async workers needed)
- No load balancing

#### Data Processing
- Crawler runs synchronously
- No background job queue
- PDF downloads block main thread
- No batch processing for bulk operations
- Limited error recovery

---

## Section 3: Collaborative Workplan (Next 30 Days)

### 3.1 Team Structure and Responsibilities

#### UNILAG Technical Team Responsibilities
1. Data quality assurance and validation
2. Faculty and department classification refinement
3. Staff member verification and updates
4. User acceptance testing
5. Institutional requirements gathering
6. Content moderation and curation
7. Training material development

#### TCC Africa / DocID Team Responsibilities
1. DocID integration architecture design
2. Read-only API access to DocID registry
3. PID resolution service integration
4. Multi-institution data standards
5. ROR identifier validation
6. Metadata schema alignment
7. Technical documentation

#### Joint Responsibilities
1. API specification and documentation
2. Data exchange format standardization
3. Security and authentication design
4. Deployment architecture
5. Performance optimization
6. Quality assurance testing
7. User interface refinement

### 3.2 Week-by-Week Workplan

#### Week 1 (April 26 - May 2, 2026): Foundation and Integration Design

**UNILAG Team Tasks**:
- Document current data quality issues and gaps
- Compile list of additional African institutions for comparison
- Gather requirements for senate report format and content
- Identify key stakeholders for user acceptance testing
- Prepare sample datasets for testing

**TCC Africa Team Tasks**:
- Review current ROR implementation and provide feedback
- Design DocID read-only integration architecture
- Specify API endpoints for DocID lookup and validation
- Document metadata mapping between systems
- Provide test DocID dataset for integration testing

**Joint Tasks**:
- Kickoff meeting to align on technical approach
- Review and approve API specifications
- Establish communication channels (Slack, email, weekly calls)
- Define success criteria for integration
- Create shared technical documentation repository

**Deliverables**:
- Integration architecture document
- API specification v1.0
- Communication protocol established
- Test dataset prepared
- Requirements document finalized

#### Week 2 (May 3 - May 9, 2026): DocID Integration and Data Expansion

**UNILAG Team Tasks**:
- Add 2-3 additional Nigerian universities to database
- Validate and clean existing UNILAG dataset
- Implement institutional branding for reports
- Conduct internal testing of comparator features
- Document user workflows and pain points

**TCC Africa Team Tasks**:
- Implement DocID lookup API endpoint
- Provide authentication credentials for read-only access
- Develop PID resolution service integration
- Create DocID validation rules and error handling
- Prepare integration testing environment

**Joint Tasks**:
- Integrate DocID lookup into paper ingestion pipeline
- Test DocID assignment and validation
- Implement error handling for DocID operations
- Conduct integration testing
- Review and refine metadata mapping

**Deliverables**:
- DocID integration functional
- 3 institutions in comparison database
- Integration test results documented
- Error handling implemented
- Metadata alignment confirmed

#### Week 3 (May 10 - May 16, 2026): Visualization and Reporting Enhancement

**UNILAG Team Tasks**:
- Gather collaboration data between Nigerian universities
- Test senate report generation with real stakeholders
- Provide feedback on report format and content
- Identify additional metrics needed for decision-making
- Prepare training materials for end users

**TCC Africa Team Tasks**:
- Implement collaboration mesh data API
- Provide geographic coordinates for African institutions
- Design visualization data format specification
- Review and approve D3.js implementation approach
- Provide sample collaboration network data

**Joint Tasks**:
- Implement D3.js collaboration mesh visualization
- Develop PDF report generation with ReportLab
- Embed charts and graphs in PDF reports
- Test report generation with multiple institutions
- Refine visualization based on user feedback

**Deliverables**:
- Collaboration mesh visualization operational
- PDF report generation functional
- Charts embedded in reports
- Geographic map prototype
- User training materials v1.0

#### Week 4 (May 17 - May 23, 2026): Security, Performance, and Production Readiness

**UNILAG Team Tasks**:
- Define user roles and access control requirements
- Test system performance with larger datasets
- Conduct user acceptance testing with stakeholders
- Document institutional policies for data access
- Prepare production deployment checklist

**TCC Africa Team Tasks**:
- Implement OAuth authentication with ORCID
- Design role-based access control system
- Provide security best practices documentation
- Review deployment architecture for production
- Conduct security audit of API endpoints

**Joint Tasks**:
- Implement authentication and authorization
- Migrate from SQLite to PostgreSQL
- Implement Redis caching layer
- Conduct load testing and performance optimization
- Deploy to staging environment
- Conduct end-to-end testing

**Deliverables**:
- Authentication system operational
- PostgreSQL migration complete
- Caching layer implemented
- Staging environment deployed
- Security audit report
- Performance test results

#### Week 5 (May 24 - May 30, 2026): Final Testing and Documentation

**UNILAG Team Tasks**:
- Conduct final user acceptance testing
- Prepare presentation materials for UNESCO
- Document institutional workflows
- Train key users and administrators
- Gather feedback for future enhancements

**TCC Africa Team Tasks**:
- Finalize API documentation with Swagger/OpenAPI
- Create developer onboarding guide
- Document DocID integration for other institutions
- Prepare technical architecture documentation
- Conduct final security review

**Joint Tasks**:
- Complete comprehensive testing (functional, integration, performance)
- Finalize all documentation
- Prepare production deployment plan
- Conduct dry-run of UNESCO presentation
- Create maintenance and support plan
- Deploy to production environment

**Deliverables**:
- Production system deployed
- Complete technical documentation
- API documentation published
- User training completed
- UNESCO presentation ready
- Maintenance plan established

### 3.3 Technical Milestones

#### Milestone 1: DocID Integration Complete (End of Week 2)
- DocID lookup functional
- PID resolution operational
- Metadata alignment verified
- Integration tests passing

#### Milestone 2: Multi-Institution Comparison Operational (End of Week 3)
- 5+ institutions in database
- Comparator generating accurate results
- Visualizations functional
- PDF reports generating

#### Milestone 3: Production-Ready System (End of Week 4)
- Authentication implemented
- Performance optimized
- Security audit passed
- Staging deployment successful

#### Milestone 4: UNESCO Presentation Ready (End of Week 5)
- Production system live
- Documentation complete
- Presentation materials prepared
- User training conducted

---

## Section 4: Technical Specifications for Collaboration

### 4.1 DocID Integration Requirements

#### Read-Only API Access
**Required Endpoints**:
- `GET /docid/lookup/{identifier}` - Lookup paper by DOI, URL, or title
- `GET /docid/validate/{docid}` - Validate DocID format and existence
- `GET /docid/resolve/{docid}` - Resolve DocID to metadata
- `GET /docid/institution/{ror}` - Get all DocIDs for an institution

**Authentication**:
- API key-based authentication
- Rate limiting: 100 requests per minute
- HTTPS required
- IP whitelisting optional

**Response Format**:
```json
{
  "docid": "20.500.14351/abc123",
  "doi": "10.1234/example",
  "title": "Paper Title",
  "authors": ["Author 1", "Author 2"],
  "institution_ror": "https://ror.org/03qcnxw14",
  "publication_date": "2024-01-15",
  "metadata": {
    "dc.title": "Paper Title",
    "dc.identifier.uri": "https://example.com/paper"
  }
}
```

#### Error Handling
- 404: DocID not found
- 400: Invalid DocID format
- 401: Authentication failed
- 429: Rate limit exceeded
- 503: Service unavailable

### 4.2 Data Exchange Standards

#### Metadata Schema
- Dublin Core compliance required
- ROR identifiers for all institutions
- ISO 8601 date formats
- UTF-8 encoding
- JSON as primary exchange format

#### Required Fields
- Title (dc.title)
- Authors (dc.contributor.author)
- Publication date (dc.date.issued)
- Institution ROR (custom field)
- DOI (dc.identifier.doi) if available
- Abstract (dc.description.abstract) if available

#### Optional Fields
- DocID (custom field)
- Patent ID (custom field)
- TK label (custom field)
- Language code (dc.language.iso)
- Content type (dc.type)

### 4.3 Infrastructure Requirements

#### Development Environment
- Python 3.9+
- PostgreSQL 15+
- Redis 7+ (for caching)
- Git for version control
- Docker for containerization

#### Production Environment
- Cloud hosting (Render, AWS, Azure, or GCP)
- PostgreSQL managed database
- Redis managed cache
- CDN for static assets
- SSL/TLS certificates
- Backup and disaster recovery

#### Monitoring and Logging
- Application performance monitoring
- Error tracking and alerting
- Access logs for security audit
- Database query performance monitoring
- API usage analytics

---

## Section 5: Risk Assessment and Mitigation

### 5.1 Technical Risks

#### Risk 1: DocID Integration Delays
**Impact**: High
**Probability**: Medium
**Mitigation**:
- Begin integration design in Week 1
- Use mock API for parallel development
- Establish clear API contract early
- Regular sync meetings between teams

#### Risk 2: Data Quality Issues
**Impact**: High
**Probability**: Medium
**Mitigation**:
- Implement comprehensive validation rules
- Manual review process for critical data
- Automated quality checks in pipeline
- Regular data audits

#### Risk 3: Performance Bottlenecks
**Impact**: Medium
**Probability**: Medium
**Mitigation**:
- Early load testing with realistic datasets
- Implement caching strategy
- Database query optimization
- Asynchronous processing for heavy operations

#### Risk 4: Security Vulnerabilities
**Impact**: High
**Probability**: Low
**Mitigation**:
- Security audit before production
- Follow OWASP best practices
- Regular dependency updates
- Penetration testing

#### Risk 5: Scope Creep
**Impact**: Medium
**Probability**: High
**Mitigation**:
- Clear milestone definitions
- Weekly progress reviews
- Prioritized feature list
- Defer non-critical features to Phase 2

### 5.2 Organizational Risks

#### Risk 1: Communication Gaps
**Impact**: Medium
**Probability**: Medium
**Mitigation**:
- Daily async updates via Slack
- Weekly video calls
- Shared documentation repository
- Clear escalation path

#### Risk 2: Resource Availability
**Impact**: High
**Probability**: Low
**Mitigation**:
- Identify backup team members
- Document all decisions and code
- Cross-training between teams
- Buffer time in schedule

---

## Section 6: Success Criteria

### 6.1 Technical Success Criteria

1. DocID integration functional with 99% uptime
2. Multi-institution comparison supporting 10+ institutions
3. Response time under 2 seconds for all API endpoints
4. PDF report generation under 10 seconds
5. Zero critical security vulnerabilities
6. 95% test coverage for core functionality
7. Database supporting 10,000+ papers without performance degradation

### 6.2 User Success Criteria

1. University administrators can generate senate reports independently
2. Researchers can discover papers across institutions
3. System accessible 24/7 with 99% uptime
4. User training completed for 10+ stakeholders
5. Positive feedback from UNESCO presentation
6. Adoption by 3+ African institutions within 3 months

### 6.3 Business Success Criteria

1. Platform demonstrates value for research leadership decision-making
2. Clear differentiation from Western platforms (Scopus, Web of Science)
3. Scalable architecture supporting 50+ institutions
4. Sustainable maintenance and support model established
5. Roadmap for Phase 2 features approved

---

## Section 7: Post-Implementation Support

### 7.1 Maintenance Plan

#### UNILAG Team Responsibilities
- Content moderation and curation
- User support and training
- Data quality monitoring
- Feature requests and prioritization
- Institutional liaison

#### TCC Africa Team Responsibilities
- Infrastructure monitoring and maintenance
- DocID registry updates and synchronization
- Security patches and updates
- Performance optimization
- Technical support escalation

#### Joint Responsibilities
- Bug fixes and issue resolution
- Feature development and enhancement
- Documentation updates
- User feedback analysis
- Quarterly system reviews

### 7.2 Support Channels

**For Technical Issues**:
- Email: support@apa-platform.org
- Slack: #apa-platform-support
- Issue tracker: GitHub/GitLab

**For DocID Issues**:
- Email: docid-support@tccafrica.org
- Documentation: https://docid.tccafrica.org/docs

**For Urgent Issues**:
- On-call rotation between teams
- 24-hour response time for critical issues
- Escalation to team leads

### 7.3 Training and Documentation

**User Documentation**:
- User guide for administrators
- Video tutorials for common tasks
- FAQ and troubleshooting guide
- Best practices for data quality

**Technical Documentation**:
- API reference with examples
- Architecture documentation
- Deployment guide
- Database schema documentation
- Integration guide for new institutions

**Training Sessions**:
- Administrator training (4 hours)
- Researcher training (2 hours)
- Technical team training (8 hours)
- Quarterly refresher sessions

---

## Section 8: Future Enhancements (Phase 2)

### 8.1 Planned Features

#### Advanced Analytics
- Predictive analytics for research trends
- Machine learning for paper classification
- Citation network analysis
- Impact factor calculation
- Collaboration recommendation engine

#### Enhanced Visualizations
- Interactive geographic maps
- Timeline visualizations
- Network graphs with filtering
- Custom dashboard builder
- Export to PowerPoint

#### Multi-Language Support
- French interface
- Portuguese interface
- Arabic interface
- Swahili interface
- Automatic translation of metadata

#### Mobile Application
- iOS and Android apps
- Offline access to saved papers
- Push notifications for new papers
- Mobile-optimized comparator

#### Integration Expansion
- ORCID bidirectional sync
- Crossref event data integration
- Altmetric score tracking
- Mendeley integration
- Zotero plugin

### 8.2 Research Opportunities

#### Collaborative Research Projects
- Pan-African research output analysis
- Indigenous knowledge preservation study
- Open access adoption trends
- Innovation commercialization patterns
- Linguistic diversity in African research

#### Publications
- Technical paper on novel metrics
- Case study on multi-institution comparison
- Best practices for institutional repositories
- Data sovereignty in research infrastructure

---

## Section 9: Budget and Resources

### 9.1 Infrastructure Costs (Monthly)

**Development Environment**:
- Cloud hosting: $0 (local development)
- Database: $0 (SQLite)
- Total: $0/month

**Production Environment**:
- Cloud hosting (Render/AWS): $50-100/month
- PostgreSQL managed database: $25-50/month
- Redis cache: $15-30/month
- CDN and storage: $10-20/month
- SSL certificates: $0 (Let's Encrypt)
- Monitoring tools: $20-40/month
- Total: $120-240/month

### 9.2 Personnel Time Allocation

**UNILAG Team** (estimated hours per week):
- Lead developer: 20 hours
- Data curator: 10 hours
- QA tester: 10 hours
- Project manager: 5 hours
- Total: 45 hours/week

**TCC Africa Team** (estimated hours per week):
- Lead developer: 15 hours
- DevOps engineer: 10 hours
- Technical architect: 5 hours
- Project manager: 5 hours
- Total: 35 hours/week

**Total Project Effort**: 80 hours/week for 5 weeks = 400 hours

---

## Section 10: Conclusion

The APA Intelligence & Analytics Platform has successfully completed its initial development phase with core infrastructure operational, novel African-focused metrics implemented, and multi-institution comparison capability established. The platform represents a significant advancement in research intelligence for African universities, providing strategic decision-making tools that do not exist in Western platforms.

The collaborative workplan outlined in this document provides a structured approach for UNILAG and TCC Africa technical teams to work together over the next 30 days to complete DocID integration, enhance visualization capabilities, implement security measures, and prepare the platform for production deployment and UNESCO presentation.

Success depends on clear communication, adherence to the weekly workplan, and commitment from both teams to deliver a world-class platform that serves African research institutions and advances the mission of the Africa PID Alliance.

---

## Appendices

### Appendix A: Technical Stack Summary

**Backend**:
- Python 3.9+
- Flask 3.0 (web framework)
- SQLAlchemy 2.0 (ORM)
- Scrapy 2.11 (web crawling)
- Gunicorn (WSGI server)

**Frontend**:
- HTML5, CSS3, JavaScript
- Tailwind CSS (utility framework)
- Chart.js (basic charts)
- D3.js (advanced visualizations)
- Socket.IO (real-time updates)

**Database**:
- SQLite (development)
- PostgreSQL 15+ (production)
- Redis 7+ (caching)

**Infrastructure**:
- Docker (containerization)
- Git (version control)
- Render/AWS (cloud hosting)

### Appendix B: API Endpoint Reference

**Comparator Endpoints**:
- `POST /api/comparator/compare`
- `POST /api/comparator/collaboration-mesh`
- `POST /api/comparator/senate-report`

**Analytics Endpoints**:
- `GET /api/analytics/tk-vitality-score`
- `GET /api/analytics/linguistic-diversity-index`
- `GET /api/analytics/patent-velocity`
- `GET /api/analytics/docid-coverage`
- `GET /api/analytics/overview`
- `GET /api/analytics/publications-by-year`
- `GET /api/analytics/papers-by-faculty`
- `GET /api/analytics/top-authors`

**Search Endpoints**:
- `GET /api/search/advanced`
- `GET /api/analytics/search`

**Paper Endpoints**:
- `GET /api/papers/tree`
- `GET /api/papers/{id}`
- `GET /api/papers/{id}/download`
- `GET /api/papers/{id}/bibtex`

**Export Endpoints**:
- `GET /api/export/papers.csv`
- `GET /api/export/papers.bibtex`

### Appendix C: Database Schema Diagram

```
Communities (Faculties)
+-- id (PK)
+-- name
+-- description
+-- created_at

Collections (Departments)
+-- id (PK)
+-- community_id (FK)
+-- name
+-- description
+-- created_at

Items (Papers)
+-- id (PK)
+-- title
+-- abstract
+-- doi
+-- ror (Institution ROR ID)
+-- institution
+-- content_type (for TK Vitality)
+-- tk_label
+-- patent_id
+-- patent_date
+-- language_code
+-- is_african_language
+-- docid
+-- publication_date
+-- created_at

Authors
+-- id (PK)
+-- name
+-- created_at

Files (PDFs)
+-- id (PK)
+-- item_id (FK)
+-- file_path
+-- sha256_hash
+-- access_policy
+-- created_at
```

### Appendix D: Contact Information

**UNILAG Technical Team**:
- Project Lead: [Name, Email]
- Lead Developer: [Name, Email]
- Data Curator: [Name, Email]

**TCC Africa / DocID Team**:
- Project Lead: [Name, Email]
- Technical Architect: [Name, Email]
- DevOps Engineer: [Name, Email]

**Project Communication**:
- Slack Workspace: [URL]
- Email List: [Email]
- Documentation: [URL]
- Issue Tracker: [URL]

---

**Document Prepared By**: Technical Team
**Review Date**: April 25, 2026
**Next Review**: May 2, 2026
**Approval Status**: Pending Joint Review
