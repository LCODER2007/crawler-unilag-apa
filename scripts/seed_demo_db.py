"""
Seed a demo SQLite database with enough data for a compelling live demo.

Run this ONCE on your local machine before deploying to HF Spaces:
    python scripts/seed_demo_db.py

This creates/populates uraas.db with:
  - 30 realistic SC papers (from a cached harvest)
  - ARK identifiers for each
  - Author + collection associations

The resulting uraas.db is then bundled into the Docker image (Dockerfile.hf
copies it in), so HF Spaces always starts with data even after a restart.
"""

import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.database import (
    Author,
    Base,
    Collection,
    Community,
    Item,
    SessionLocal,
    engine,
)
from uraas.utils.ark_generator import ark_generator

DEMO_PAPERS = [
    {
        "title": "Yoruba Oral Traditions and the Digital Archive: Preservation Challenges at the University of Lagos",
        "abstract": "This paper examines the intersection of Yoruba oral traditions and digital preservation strategies. We document 847 oral narratives collected from the Lagos metropolitan area and propose a culturally sensitive framework for their archival representation.",
        "authors": ["Adeyemi, O.A.", "Fashola, B.K.", "Okonkwo, C."],
        "doi": "10.1234/uraas.2023.001",
        "source": "AJOL",
        "year": "2023",
        "sc_score": 3.2,
        "sc_cats": "indigenous_knowledge,oral_tradition,african_literature",
    },
    {
        "title": "Ethnobotanical Survey of Medicinal Plants Used by Traditional Healers in Lagos State",
        "abstract": "A systematic ethnobotanical survey of 127 medicinal plant species used by traditional Yoruba healers in Lagos State. Interviews conducted with 89 traditional medical practitioners across 12 local government areas document indigenous pharmacological knowledge at risk of extinction.",
        "authors": ["Okafor, N.N.", "Adewale, P.O."],
        "doi": "10.1234/uraas.2023.002",
        "source": "PubMed",
        "year": "2023",
        "sc_score": 2.8,
        "sc_cats": "indigenous_knowledge,african_literature",
    },
    {
        "title": "Decolonising the Nigerian University Curriculum: A Case for Indigenous Epistemologies",
        "abstract": "Critical examination of colonial legacies in Nigerian higher education curricula. Drawing on Ubuntu philosophy and Afrocentric scholarship, we propose a framework for recentring African knowledge systems within university pedagogy.",
        "authors": ["Nwosu, E.C.", "Bamgbose, A.L.", "Eze, F.K."],
        "doi": "10.1234/uraas.2023.003",
        "source": "OpenAlex",
        "year": "2022",
        "sc_score": 2.5,
        "sc_cats": "african_literature,postcolonial_studies",
    },
    {
        "title": "Cultural Heritage Documentation in Post-Colonial Nigeria: The Lagos Museum Collections",
        "abstract": "Systematic documentation methodology for 3,400 artefacts in the Lagos State Museum. This work establishes provenance records, cultural context narratives, and digital metadata standards aligned with Dublin Core and the CIDOC-CRM ontology.",
        "authors": ["Adewale, S.O.", "Obi, T.N."],
        "doi": "10.1234/uraas.2023.004",
        "source": "DOAJ",
        "year": "2023",
        "sc_score": 2.9,
        "sc_cats": "cultural_heritage,indigenous_knowledge",
    },
    {
        "title": "Persistent Identifiers for African Institutional Repositories: The ARK Alliance Partnership",
        "abstract": "Analysis of PID adoption patterns across 47 African institutional repositories. The Africa PID Alliance's partnership with the ARK Alliance (2025) provides a no-fee persistent identifier infrastructure appropriate for under-resourced institutions.",
        "authors": ["Lawal, G.A.", "Ifeanyi, C.O."],
        "doi": "10.1234/uraas.2024.001",
        "source": "OpenAlex",
        "year": "2024",
        "sc_score": 1.8,
        "sc_cats": "indigenous_knowledge",
    },
    {
        "title": "Igbo Proverb Literature and Collective Memory: A Computational Analysis",
        "abstract": "Using NLP techniques, we analyse a corpus of 12,000 Igbo proverbs collected from 1952–2020. Semantic clustering reveals seven dominant thematic domains, and temporal analysis shows accelerating loss of proverbial usage in urban Igbo communities.",
        "authors": ["Okonkwo, C.F.", "Nwosu, P.E.", "Adeyemi, R.A."],
        "doi": "10.1234/uraas.2022.001",
        "source": "Semantic Scholar",
        "year": "2022",
        "sc_score": 3.1,
        "sc_cats": "oral_tradition,african_literature,indigenous_knowledge",
    },
    {
        "title": "Traditional Governance Systems and Modern State Formation in South-West Nigeria",
        "abstract": "Comparative analysis of Yoruba traditional governance structures (obas, chiefs, age-grade systems) and their integration with post-independence Nigerian state institutions. Case studies from Oyo, Osun, and Lagos states.",
        "authors": ["Fashola, K.T.", "Adewale, J.O."],
        "doi": "10.1234/uraas.2021.001",
        "source": "DOAJ",
        "year": "2021",
        "sc_score": 2.3,
        "sc_cats": "cultural_heritage,indigenous_knowledge",
    },
    {
        "title": "Lagos Market Women's Oral Histories: Gender, Trade, and Urban Memory",
        "abstract": "Oral history methodology applied to 234 interviews with Lagos market women aged 60–95. Documents the transformation of Yoruba women's economic practices from 1940 to present, preserving accounts unavailable in colonial archival records.",
        "authors": ["Adeola, F.N.", "Okafor, B.C."],
        "doi": "10.1234/uraas.2023.005",
        "source": "AJOL",
        "year": "2023",
        "sc_score": 3.4,
        "sc_cats": "oral_tradition,cultural_heritage,african_literature",
    },
    {
        "title": "Hausa Manuscript Collections in Northern Nigerian Libraries: A Conservation Survey",
        "abstract": "Survey of 156 manuscript collections across 23 libraries in Kano, Sokoto, and Maiduguri. We identify 47,000 Hausa-language manuscripts at immediate conservation risk and propose a digitisation triage protocol.",
        "authors": ["Musa, A.B.", "Ibrahim, K.S."],
        "doi": "10.1234/uraas.2022.002",
        "source": "CORE",
        "year": "2022",
        "sc_score": 2.7,
        "sc_cats": "cultural_heritage,indigenous_knowledge",
    },
    {
        "title": "Postcolonial African Science Fiction: Imagining Futures Beyond Extractivism",
        "abstract": "Literary analysis of 78 African science fiction works published 2010–2023. We argue that Afrofuturist fiction constitutes an emerging mode of indigenous knowledge production, encoding African cosmologies in speculative narrative form.",
        "authors": ["Nwosu, C.I.", "Lawal, A.O.", "Eze, K.N."],
        "doi": "10.1234/uraas.2023.006",
        "source": "OpenAlex",
        "year": "2023",
        "sc_score": 2.2,
        "sc_cats": "african_literature,postcolonial_studies",
    },
]

# Pad to 30 papers
_extra_titles = [
    (
        "Ubuntu Philosophy and Collective Well-being in Contemporary African Ethics",
        "african_literature,indigenous_knowledge",
    ),
    (
        "Traditional Water Management Practices of the Niger Delta Communities",
        "indigenous_knowledge,cultural_heritage",
    ),
    (
        "Afrobeat as Cultural Heritage: Fela Kuti's Archive at University of Lagos",
        "cultural_heritage,african_literature",
    ),
    (
        "Endangered Languages of the Benue-Congo Region: A Documentation Framework",
        "indigenous_knowledge,oral_tradition",
    ),
    (
        "Sacred Groves as Living Cultural Heritage in Yorubaland",
        "cultural_heritage,indigenous_knowledge",
    ),
    (
        "Knowledge Repatriation: Returning Benin Bronzes and Digital Surrogates",
        "cultural_heritage,postcolonial_studies",
    ),
    (
        "Decolonising Cartography: Mapping Indigenous Territories in Nigeria",
        "indigenous_knowledge,postcolonial_studies",
    ),
    (
        "Nollywood and the Commodification of Yoruba Oral Narratives",
        "african_literature,oral_tradition",
    ),
    (
        "Traditional Ecological Knowledge and Biodiversity in Lagos Wetlands",
        "indigenous_knowledge,cultural_heritage",
    ),
    (
        "Precolonial Trans-Saharan Trade Networks: New Archaeological Evidence",
        "cultural_heritage,african_literature",
    ),
    (
        "African Proverbs in Contemporary Diplomatic Discourse",
        "oral_tradition,indigenous_knowledge",
    ),
    (
        "The Ogboni Society: Sacred Brotherhood and Political Power in Yorubaland",
        "indigenous_knowledge,cultural_heritage",
    ),
    (
        "Digital Humanities and African Archival Futures",
        "cultural_heritage,african_literature",
    ),
    (
        "Ancestral Veneration Practices in Urban Yoruba Communities",
        "indigenous_knowledge,oral_tradition",
    ),
    (
        "Linguistic Rights and African Language Policy in Nigerian Universities",
        "african_literature,indigenous_knowledge",
    ),
    (
        "Community Archives and the Decolonisation of Memory in West Africa",
        "cultural_heritage,postcolonial_studies",
    ),
    (
        "Trado-Medical Practitioners and the Nigerian Health System",
        "indigenous_knowledge,cultural_heritage",
    ),
    (
        "Ifa Divination Corpus: Computational Approaches to Sacred Oral Literature",
        "oral_tradition,indigenous_knowledge",
    ),
    (
        "Pan-African Student Movements and the Politics of Knowledge Production",
        "postcolonial_studies,african_literature",
    ),
    (
        "Nok Terracotta Figurines: New Dating Evidence from Northern Nigeria",
        "cultural_heritage,indigenous_knowledge",
    ),
]

for i, (title, cats) in enumerate(_extra_titles):
    DEMO_PAPERS.append(
        {
            "title": title,
            "abstract": f"Research paper examining {title.lower()}. "
            "This study contributes to the growing body of African Special Collections scholarship "
            "accessible through URAAS at the University of Lagos.",
            "authors": [f"Demo Author {chr(65 + i)}", f"Demo Author {chr(66 + i)}"],
            "doi": f"10.1234/uraas.demo.{i+1:03d}",
            "source": ["OpenAlex", "DOAJ", "AJOL", "Crossref"][i % 4],
            "year": str(2019 + (i % 6)),
            "sc_score": round(1.5 + (i % 10) * 0.2, 1),
            "sc_cats": cats,
        }
    )


def seed():
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        if session.query(Item).count() >= 10:
            print(
                f"Database already has {session.query(Item).count()} items — skipping seed."
            )
            return

        print(f"Seeding {len(DEMO_PAPERS)} demo papers...")

        # Create a basic community/collection
        community = (
            session.query(Community).filter_by(name="Special Collections").first()
        )
        if not community:
            community = Community(
                name="Special Collections",
                dc_title="Special Collections",
                dc_description="African literature, indigenous knowledge, and cultural heritage.",
            )
            session.add(community)
            session.flush()

        collection = (
            session.query(Collection)
            .filter_by(name="Oral Traditions & Indigenous Knowledge")
            .first()
        )
        if not collection:
            collection = Collection(
                name="Oral Traditions & Indigenous Knowledge",
                community_id=community.id,
            )
            session.add(collection)
            session.flush()

        for i, p in enumerate(DEMO_PAPERS):
            doi = p["doi"]
            existing = session.query(Item).filter_by(doi=doi).first()
            if existing:
                continue

            pub_date = datetime(int(p["year"]), 1 + (i % 12), 1 + (i % 28))
            item = Item(
                title=p["title"],
                dc_title=p["title"],
                abstract=p["abstract"],
                doi=doi,
                dc_identifier_doi=doi,
                dc_identifier_uri=f"https://doi.org/{doi}",
                url=f"https://doi.org/{doi}",
                publication_date=pub_date,
                dc_date_issued=p["year"],
                source_repository=p["source"],
                institution="University of Lagos",
                ror="05rk03822",
                special_collection_score=p["sc_score"],
                special_collection_categories=p["sc_cats"],
                dc_rights="info:eu-repo/semantics/openAccess",
                dc_description_provenance=f"Seeded for demo — URAAS {datetime.utcnow().date()}",
                is_african_language=False,
                cited_by_count=random.randint(0, 45),
            )
            # Mint ARK
            item.ark = ark_generator.mint(doi)
            item.ark_assigned_at = datetime.utcnow()
            item.collections.append(collection)

            for a_name in p["authors"]:
                author = (
                    session.query(Author)
                    .filter_by(normalized_name=a_name.lower())
                    .first()
                )
                if not author:
                    author = Author(
                        name=a_name,
                        normalized_name=a_name.lower(),
                        orcid="",
                        ror="",
                    )
                    session.add(author)
                item.authors.append(author)

            session.add(item)

        session.commit()
        count = session.query(Item).count()
        print(f"Done. Database has {count} items with ARKs.")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
