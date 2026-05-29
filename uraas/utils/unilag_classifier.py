"""
URAAS UNILAG Academic Classifier — Production Grade
=====================================================
Features:
  - TF-IDF–style weighted keyword scoring (rare/specific keywords score higher)
  - Multi-word phrase detection with word boundary matching
  - Inverse-document-frequency (IDF) weighting across departments
  - SDG (UN Sustainable Development Goals 1–17) alignment detection
  - classify_with_explanation() for transparency and debugging
  - Full 2024 UNILAG Faculty & Department structure
"""

import math
import re
from typing import Any, Dict, List, Optional, Tuple

# ─── Complete UNILAG Faculty and Department Structure (2024) ───────────────────
UNILAG_STRUCTURE = {
    "Faculty of Arts": {
        "Creative Arts": [
            "creative arts",
            "theatre",
            "drama",
            "performance",
            "visual arts",
            "music",
            "dance",
            "cinematography",
            "costume design",
            "stage design",
            "african theatre",
            "yoruba drama",
            "nollywood",
            "film studies",
        ],
        "English": [
            "english literature",
            "linguistics",
            "language studies",
            "literary criticism",
            "phonetics",
            "morphology",
            "syntax",
            "pragmatics",
            "discourse analysis",
            "stylistics",
            "narrative theory",
            "african literature in english",
            "postcolonial literature",
        ],
        "History and Strategic Studies": [
            "history",
            "strategic studies",
            "military",
            "warfare",
            "historical analysis",
            "colonialism",
            "decolonization",
            "lagos history",
            "nigerian history",
            "precolonial",
            "empire",
            "slave trade",
            "nationalism",
        ],
        "Philosophy": [
            "philosophy",
            "logic",
            "ethics",
            "metaphysics",
            "epistemology",
            "african philosophy",
            "political philosophy",
            "philosophy of mind",
            "existentialism",
            "ontology",
            "moral philosophy",
        ],
        "Languages": [
            "french",
            "german",
            "russian",
            "arabic",
            "foreign language",
            "translation",
            "language pedagogy",
            "yoruba",
            "igbo",
            "hausa",
            "pidgin",
            "nigerian languages",
            "oral tradition",
            "indigenous language",
            "language policy",
            "multilingualism",
            "sociolinguistics",
        ],
    },
    "Faculty of Science": {
        "Biochemistry": [
            "biochemistry",
            "molecular biology",
            "enzymology",
            "metabolism",
            "protein",
            "lipid",
            "carbohydrate",
            "enzyme kinetics",
            "dna replication",
            "gene expression",
            "proteomics",
            "metabolomics",
            "oxidative stress",
        ],
        "Botany": [
            "botany",
            "plant biology",
            "plant physiology",
            "taxonomy",
            "flora",
            "phytology",
            "seed germination",
            "photosynthesis",
            "ethnobotany",
            "mangrove",
            "rainforest ecology",
            "medicinal plants",
        ],
        "Cell Biology and Genetics": [
            "cell biology",
            "genetics",
            "cytology",
            "heredity",
            "dna",
            "gene expression",
            "chromosome",
            "genetic mutation",
            "stem cell",
            "epigenetics",
            "genomics",
            "bioinformatics",
            "crispr",
            "pcr",
        ],
        "Chemistry": [
            "chemistry",
            "organic chemistry",
            "inorganic chemistry",
            "analytical chemistry",
            "chemical",
            "spectroscopy",
            "chromatography",
            "electrochemistry",
            "polymer chemistry",
            "green chemistry",
            "natural product chemistry",
            "phytochemical",
            "coordination chemistry",
        ],
        "Computer Science": [
            "computer science",
            "machine learning",
            "artificial intelligence",
            "software engineering",
            "data science",
            "algorithm",
            "programming",
            "neural network",
            "deep learning",
            "natural language processing",
            "computer vision",
            "cloud computing",
            "cybersecurity",
            "blockchain",
            "distributed systems",
            "database",
            "internet of things",
            "iot",
            "big data",
            "data mining",
            "robotics",
            "human computer interaction",
        ],
        "Geosciences": [
            "geology",
            "geophysics",
            "earth science",
            "mineralogy",
            "petrology",
            "stratigraphy",
            "sedimentology",
            "remote sensing",
            "gis",
            "hydrogeology",
            "seismology",
            "geochemistry",
            "oil sand",
            "crude oil",
        ],
        "Marine Sciences": [
            "marine biology",
            "oceanography",
            "aquatic",
            "fisheries",
            "coastal",
            "lagos lagoon",
            "atlantic ocean",
            "mangrove ecology",
            "coral reef",
            "tidal",
            "estuarine",
            "plankton",
            "benthic",
            "aquaculture",
        ],
        "Mathematics": [
            "mathematics",
            "algebra",
            "calculus",
            "topology",
            "geometry",
            "statistics",
            "probability",
            "number theory",
            "differential equations",
            "numerical analysis",
            "mathematical modeling",
            "stochastic process",
            "optimization",
            "combinatorics",
            "graph theory",
        ],
        "Microbiology": [
            "microbiology",
            "bacteriology",
            "virology",
            "mycology",
            "microorganism",
            "antimicrobial",
            "antibiotic resistance",
            "pathogen",
            "bacterial infection",
            "fungal",
            "fermentation",
            "probiotics",
            "microbiome",
            "food microbiology",
        ],
        "Physics": [
            "physics",
            "quantum",
            "thermodynamics",
            "optics",
            "mechanics",
            "astrophysics",
            "particle physics",
            "condensed matter",
            "semiconductor",
            "laser",
            "plasma physics",
            "nuclear physics",
            "solid state physics",
            "electromagnetic",
            "radiation",
        ],
        "Zoology": [
            "zoology",
            "animal biology",
            "entomology",
            "parasitology",
            "wildlife",
            "ecology",
            "animal behavior",
            "herpetology",
            "ornithology",
            "mammalogy",
            "invertebrate",
            "vertebrate",
            "biodiversity",
        ],
    },
    "Faculty of Engineering": {
        "Chemical and Polymer Engineering": [
            "chemical engineering",
            "polymer",
            "petrochemical",
            "process engineering",
            "distillation",
            "reaction kinetics",
            "unit operations",
            "petroleum refining",
            "biofuel",
            "nanomaterial synthesis",
        ],
        "Civil and Environmental Engineering": [
            "civil engineering",
            "structural",
            "concrete",
            "transportation",
            "environmental engineering",
            "geotechnical",
            "foundation",
            "highway",
            "bridge",
            "water resources",
            "hydraulics",
            "wastewater treatment",
            "solid waste",
            "urban infrastructure",
        ],
        "Electrical and Electronics Engineering": [
            "electrical engineering",
            "circuit",
            "power systems",
            "electronics",
            "telecommunications",
            "signal processing",
            "control systems",
            "embedded systems",
            "wireless communication",
            "5g",
            "microelectronics",
            "power electronics",
            "smart grid",
            "renewable energy systems",
        ],
        "Mechanical Engineering": [
            "mechanical",
            "thermofluids",
            "mechatronics",
            "manufacturing",
            "robotics",
            "turbine",
            "heat transfer",
            "fluid mechanics",
            "vibration",
            "cad",
            "finite element analysis",
            "tribology",
        ],
        "Metallurgical and Materials Engineering": [
            "metallurgy",
            "materials science",
            "corrosion",
            "alloy",
            "ceramics",
            "composite materials",
            "biomaterials",
            "fracture mechanics",
            "heat treatment",
            "welding",
            "casting",
            "nanocomposite",
        ],
        "Systems Engineering": [
            "systems engineering",
            "operations research",
            "optimization",
            "industrial engineering",
            "supply chain",
            "project management",
            "reliability engineering",
            "lean manufacturing",
            "six sigma",
        ],
    },
    "College of Medicine": {
        "Anatomy": [
            "anatomy",
            "morphology",
            "histology",
            "embryology",
            "neuroanatomy",
            "gross anatomy",
            "clinical anatomy",
        ],
        "Physiology": [
            "physiology",
            "cellular physiology",
            "metabolism",
            "homeostasis",
            "organ function",
            "cardiovascular physiology",
            "neurophysiology",
            "renal physiology",
            "endocrine physiology",
        ],
        "Pharmacology": [
            "pharmacology",
            "drug",
            "toxicology",
            "pharmacokinetics",
            "therapeutics",
            "pharmacodynamics",
            "clinical pharmacology",
            "herbal pharmacology",
            "drug interaction",
        ],
        "Morbid Anatomy": [
            "pathology",
            "autopsy",
            "forensic",
            "histopathology",
            "biopsy",
        ],
        "Chemical Pathology": [
            "clinical chemistry",
            "biochemical",
            "metabolic disorder",
            "laboratory diagnosis",
            "biomarker",
        ],
        "Haematology and Blood Transfusion": [
            "haematology",
            "blood",
            "transfusion",
            "anemia",
            "coagulation",
            "sickle cell",
            "lymphoma",
            "leukemia",
            "platelet",
        ],
        "Medical Microbiology and Parasitology": [
            "medical microbiology",
            "parasitology",
            "infectious disease",
            "antimicrobial",
            "tropical disease",
            "malaria",
            "typhoid",
            "tuberculosis",
            "hiv",
            "aids",
            "antiretroviral",
            "cholera",
            "ebola",
        ],
        "Community Health and Primary Care": [
            "public health",
            "epidemiology",
            "community medicine",
            "preventive medicine",
            "health promotion",
            "vaccination",
            "disease burden",
            "morbidity",
            "mortality",
            "determinants of health",
        ],
        "Medicine": [
            "internal medicine",
            "cardiology",
            "nephrology",
            "endocrinology",
            "gastroenterology",
            "hepatology",
            "neurology",
            "pulmonology",
            "diabetes mellitus",
            "hypertension",
            "chronic disease",
        ],
        "Obstetrics and Gynaecology": [
            "obstetrics",
            "gynaecology",
            "pregnancy",
            "maternal",
            "reproductive health",
            "antenatal",
            "postnatal",
            "caesarean",
            "eclampsia",
            "preeclampsia",
            "fertility",
            "infertility",
            "cervical cancer",
            "maternal mortality",
        ],
        "Paediatrics": [
            "paediatrics",
            "pediatrics",
            "child health",
            "neonatology",
            "infant mortality",
            "childhood malnutrition",
            "vaccination schedule",
        ],
        "Surgery": [
            "surgery",
            "surgical",
            "operation",
            "laparoscopy",
            "trauma",
            "emergency surgery",
            "neurosurgery",
            "thoracic surgery",
            "colorectal surgery",
            "vascular surgery",
        ],
        "Anaesthesia": [
            "anaesthesia",
            "anesthesia",
            "pain management",
            "critical care",
            "icu",
        ],
        "Ophthalmology": [
            "ophthalmology",
            "eye",
            "vision",
            "retina",
            "glaucoma",
            "cataract",
        ],
        "Orthopaedics and Traumatology": [
            "orthopaedics",
            "orthopedics",
            "bone",
            "fracture",
            "joint",
            "arthroplasty",
            "scoliosis",
            "osteoporosis",
            "musculoskeletal",
        ],
        "Psychiatry": [
            "psychiatry",
            "mental health",
            "psychosis",
            "depression",
            "schizophrenia",
            "anxiety disorder",
            "bipolar",
            "substance abuse",
            "post traumatic stress",
            "neurodevelopmental",
        ],
        "Radiology": [
            "radiology",
            "imaging",
            "x-ray",
            "mri",
            "ct scan",
            "ultrasound",
            "interventional radiology",
            "nuclear medicine",
            "pet scan",
        ],
    },
    "Faculty of Pharmacy": {
        "Clinical Pharmacy and Pharmacy Administration": [
            "clinical pharmacy",
            "pharmaceutical care",
            "pharmacy practice",
            "pharmacovigilance",
            "drug utilization",
            "adherence",
        ],
        "Pharmaceutical Chemistry": [
            "pharmaceutical chemistry",
            "drug synthesis",
            "medicinal chemistry",
            "structure activity relationship",
            "drug design",
            "lead compound",
        ],
        "Pharmaceutics and Pharmaceutical Technology": [
            "pharmaceutics",
            "drug formulation",
            "dosage form",
            "tablet",
            "controlled release",
            "nanoparticle drug delivery",
            "bioavailability",
        ],
        "Pharmacognosy": [
            "pharmacognosy",
            "natural products",
            "herbal medicine",
            "phytochemistry",
            "ethnopharmacology",
            "alkaloid",
            "flavonoid",
            "indigenous knowledge medicine",
            "traditional medicine",
        ],
    },
    "Faculty of Dental Sciences": {
        "Oral and Maxillofacial Surgery": [
            "oral surgery",
            "maxillofacial",
            "jaw",
            "dental surgery",
            "facial reconstruction",
            "cleft palate",
        ],
        "Preventive Dentistry": [
            "preventive dentistry",
            "oral hygiene",
            "dental public health",
            "dental caries prevention",
            "oral cancer screening",
        ],
        "Restorative Dentistry": [
            "restorative dentistry",
            "prosthodontics",
            "endodontics",
            "dental restoration",
            "crown",
            "dental implant",
        ],
        "Child Dental Health": [
            "paediatric dentistry",
            "pediatric dentistry",
            "child dental",
            "early childhood caries",
            "fluoride",
        ],
    },
    "Faculty of Basic Medical Sciences": {
        "Anatomy": ["anatomy", "morphology", "histology", "gross anatomy"],
        "Physiology": ["physiology", "cellular physiology", "organ function"],
        "Biochemistry": ["biochemistry", "molecular biology", "enzyme", "metabolism"],
    },
    "Faculty of Social Sciences": {
        "Economics": [
            "economics",
            "macroeconomics",
            "microeconomics",
            "econometrics",
            "development economics",
            "fiscal policy",
            "monetary policy",
            "economic growth",
            "poverty",
            "inequality",
            "trade policy",
            "nigerian economy",
            "african development",
        ],
        "Geography": [
            "geography",
            "gis",
            "remote sensing",
            "cartography",
            "spatial analysis",
            "land use",
            "urban geography",
            "population geography",
            "climate geography",
        ],
        "Mass Communication": [
            "mass communication",
            "journalism",
            "media",
            "broadcasting",
            "public relations",
            "advertising",
            "social media",
            "digital media",
            "media literacy",
            "press freedom",
            "fake news",
        ],
        "Political Science": [
            "political science",
            "governance",
            "democracy",
            "international relations",
            "corruption",
            "federalism",
            "electoral",
            "political party",
            "conflict resolution",
            "peacekeeping",
            "diplomacy",
        ],
        "Psychology": [
            "psychology",
            "cognitive",
            "behavioral",
            "clinical psychology",
            "educational psychology",
            "health psychology",
            "trauma",
            "counseling",
            "psychotherapy",
            "social psychology",
        ],
        "Sociology": [
            "sociology",
            "social theory",
            "social structure",
            "demography",
            "gender",
            "migration",
            "urbanization",
            "family sociology",
            "crime",
            "deviance",
            "social inequality",
        ],
    },
    "Faculty of Law": {
        "Public Law": [
            "constitutional law",
            "administrative law",
            "human rights",
            "public law",
            "electoral law",
            "environmental law",
            "petroleum law",
            "niger delta",
            "freedom of information",
        ],
        "Private and Property Law": [
            "contract law",
            "property law",
            "land law",
            "tort",
            "succession law",
            "equity",
            "customary law",
        ],
        "Commercial and Industrial Law": [
            "commercial law",
            "corporate law",
            "business law",
            "intellectual property",
            "banking law",
            "insurance law",
            "maritime law",
            "competition law",
        ],
        "International and Comparative Law": [
            "international law",
            "comparative law",
            "treaty",
            "international trade law",
            "international human rights",
            "international criminal law",
            "ecowas",
            "african union law",
        ],
    },
    "Faculty of Education": {
        "Arts and Social Sciences Education": [
            "education",
            "pedagogy",
            "curriculum",
            "teaching methods",
            "instructional design",
            "educational psychology",
            "classroom management",
        ],
        "Science and Technology Education": [
            "science education",
            "technology education",
            "stem education",
            "mathematics education",
            "physics education",
            "coding education",
        ],
        "Educational Administration": [
            "educational administration",
            "school management",
            "educational leadership",
            "policy implementation",
            "higher education management",
            "university governance",
        ],
    },
    "Faculty of Environmental Sciences": {
        "Architecture": [
            "architecture",
            "architectural design",
            "building design",
            "urban design",
            "sustainable architecture",
            "green building",
            "vernacular architecture",
            "african architecture",
        ],
        "Estate Management": [
            "estate management",
            "property valuation",
            "real estate",
            "land management",
            "property market",
            "lagos real estate",
        ],
        "Quantity Surveying": [
            "quantity surveying",
            "cost estimation",
            "construction economics",
            "bill of quantities",
            "procurement",
        ],
        "Surveying and Geoinformatics": [
            "surveying",
            "geoinformatics",
            "geodesy",
            "land surveying",
            "photogrammetry",
            "total station",
        ],
        "Urban and Regional Planning": [
            "urban planning",
            "regional planning",
            "town planning",
            "city planning",
            "master plan",
            "zoning",
            "housing policy",
            "slum upgrading",
            "smart city",
            "lagos masterplan",
        ],
    },
    "Faculty of Management Sciences": {
        "Actuarial Science and Insurance": [
            "actuarial science",
            "insurance",
            "risk management",
            "actuarial",
            "life insurance",
            "pension",
            "annuity",
        ],
        "Accounting": [
            "accounting",
            "financial accounting",
            "auditing",
            "taxation",
            "forensic accounting",
            "ifrs",
            "financial reporting",
        ],
        "Business Administration": [
            "business administration",
            "management",
            "organizational behavior",
            "strategic management",
            "entrepreneurship",
            "sme",
            "startup",
            "leadership",
            "corporate governance",
        ],
        "Employment Relations and Human Resource Management": [
            "human resource",
            "hr management",
            "industrial relations",
            "personnel management",
            "talent management",
            "employee relations",
        ],
        "Finance": [
            "finance",
            "corporate finance",
            "investment",
            "financial markets",
            "capital market",
            "stock exchange",
            "nigerian stock exchange",
            "portfolio management",
            "microfinance",
            "fintech",
        ],
    },
    "Special Collections": {
        "Indigenous Knowledge": [
            "oral traditions",
            "indigenous epistemologies",
            "ethnobotanical",
            "traditional ecological",
            "folklore storytelling",
            "ancestral wisdom",
            "indigenous languages",
            "ritual",
            "community transmission",
            "precolonial",
            "african philosophy",
            "customary law",
            "traditional medicine",
        ],
        "African Literature": [
            "african literature",
            "postcolonial literature",
            "oral literature",
            "yoruba drama",
            "igbo literature",
            "african poetry",
            "narratology",
            "literary criticism africa",
            "cultural identity memory",
            "heritage",
        ],
        "Cultural Heritage": [
            "intangible cultural heritage",
            "cultural identity memory",
            "heritage",
            "postcolonial heritage",
            "oral history",
            "traditional customs",
            "material culture",
            "sacred symbolism",
            "cultural continuity",
            "historical analysis",
            "archaeology africa",
        ],
    },
}

# ─── SDG Keyword Map (UN Sustainable Development Goals) ───────────────────────
SDG_MAP = {
    "SDG 1 — No Poverty": [
        "poverty",
        "extreme poverty",
        "social protection",
        "financial inclusion",
        "microfinance",
        "income inequality",
        "livelihood",
        "subsistence",
    ],
    "SDG 2 — Zero Hunger": [
        "food security",
        "hunger",
        "malnutrition",
        "agricultural productivity",
        "food production",
        "crop yield",
        "famine",
        "stunting",
        "wasting",
    ],
    "SDG 3 — Good Health & Well-being": [
        "health",
        "disease",
        "mortality",
        "morbidity",
        "vaccination",
        "hiv",
        "malaria",
        "tuberculosis",
        "maternal health",
        "child health",
        "cancer",
        "mental health",
        "epidemic",
        "pandemic",
        "covid",
        "universal health coverage",
    ],
    "SDG 4 — Quality Education": [
        "education",
        "literacy",
        "school enrollment",
        "learning outcomes",
        "curriculum",
        "pedagogy",
        "higher education",
        "stem education",
        "teacher training",
        "access to education",
    ],
    "SDG 5 — Gender Equality": [
        "gender equality",
        "women empowerment",
        "gender based violence",
        "gender gap",
        "female education",
        "maternal",
        "reproductive rights",
        "gender disparity",
        "patriarchy",
    ],
    "SDG 6 — Clean Water & Sanitation": [
        "water quality",
        "wastewater",
        "sanitation",
        "water treatment",
        "drinking water",
        "groundwater",
        "water pollution",
        "hygiene",
    ],
    "SDG 7 — Affordable & Clean Energy": [
        "renewable energy",
        "solar energy",
        "wind energy",
        "photovoltaic",
        "biomass",
        "energy access",
        "electricity",
        "power generation",
        "energy poverty",
        "clean cooking",
    ],
    "SDG 8 — Decent Work & Economic Growth": [
        "economic growth",
        "employment",
        "unemployment",
        "labour market",
        "gdp",
        "sme",
        "entrepreneurship",
        "productivity",
        "decent work",
    ],
    "SDG 9 — Industry, Innovation & Infrastructure": [
        "infrastructure",
        "innovation",
        "industrialization",
        "manufacturing",
        "technology transfer",
        "broadband",
        "transportation network",
        "smart city",
        "industry 4.0",
    ],
    "SDG 10 — Reduced Inequalities": [
        "inequality",
        "income gap",
        "social exclusion",
        "discrimination",
        "marginalization",
        "migrant",
        "refugee",
        "disability",
    ],
    "SDG 11 — Sustainable Cities & Communities": [
        "urban planning",
        "housing",
        "slum",
        "urbanization",
        "resilient city",
        "public transport",
        "disaster risk",
        "cultural heritage",
        "lagos",
    ],
    "SDG 12 — Responsible Consumption & Production": [
        "sustainable consumption",
        "circular economy",
        "waste management",
        "plastic pollution",
        "e-waste",
        "life cycle assessment",
        "recycling",
    ],
    "SDG 13 — Climate Action": [
        "climate change",
        "global warming",
        "carbon emission",
        "greenhouse",
        "climate adaptation",
        "mitigation",
        "deforestation",
        "flood",
        "sea level rise",
        "drought",
        "desertification",
    ],
    "SDG 14 — Life Below Water": [
        "marine",
        "ocean",
        "fisheries",
        "coastal",
        "coral reef",
        "aquatic biodiversity",
        "water pollution",
        "plastic in ocean",
        "lagos lagoon",
        "atlantic",
    ],
    "SDG 15 — Life on Land": [
        "biodiversity",
        "ecosystem",
        "deforestation",
        "land degradation",
        "endangered species",
        "wildlife",
        "forest conservation",
        "soil erosion",
        "desertification",
    ],
    "SDG 16 — Peace, Justice & Strong Institutions": [
        "governance",
        "corruption",
        "rule of law",
        "human rights",
        "conflict",
        "peacebuilding",
        "democracy",
        "transparency",
        "accountability",
        "institutional reform",
    ],
    "SDG 17 — Partnerships for the Goals": [
        "international cooperation",
        "development aid",
        "technology transfer",
        "capacity building",
        "data sharing",
        "open access",
        "south south",
        "african union",
        "ecowas",
        "global partnership",
    ],
}

# Email pattern for UNILAG staff
UNILAG_EMAIL_PATTERN = r"[a-z]+@(unilag\.edu\.ng|cmul\.edu\.ng)"


class UNILAGClassifier:
    """
    Production-grade TF-IDF–style classifier for UNILAG research papers.

    Features:
    - IDF weighting: keywords unique to one department score higher than
      keywords shared across many departments
    - Multi-word phrase detection with proper word boundary matching
    - SDG alignment mapping for UN Sustainable Development Goals
    - classify_with_explanation() for full transparency
    """

    def __init__(self):
        self.structure = UNILAG_STRUCTURE
        self._idf_weights: Dict[str, float] = {}
        self._all_keywords: Dict[str, List[Tuple[str, str]]] = (
            {}
        )  # kw -> [(faculty, dept)]
        self._build_idf_index()

    def _build_idf_index(self):
        """Pre-compute IDF weights for all keywords across departments."""
        # Count how many (faculty, dept) pairs contain each keyword
        kw_doc_counts: Dict[str, int] = {}
        total_depts = 0

        for faculty, departments in self.structure.items():
            for dept, keywords in departments.items():
                total_depts += 1
                for kw in keywords:
                    kw_lower = kw.lower()
                    kw_doc_counts[kw_lower] = kw_doc_counts.get(kw_lower, 0) + 1
                    if kw_lower not in self._all_keywords:
                        self._all_keywords[kw_lower] = []
                    self._all_keywords[kw_lower].append((faculty, dept))

        # Compute IDF: log(N / df) — rarer keywords get higher weight
        for kw, df in kw_doc_counts.items():
            self._idf_weights[kw] = math.log(total_depts / df) + 1.0

    def _score_keyword(self, kw: str, matches: int) -> float:
        """
        Compute TF-IDF–style score for a keyword.
        - Match count (TF proxy): log(1 + matches)
        - IDF weight: log(N/df) + 1
        - Length bonus: longer multi-word phrases are more specific
        """
        if matches == 0:
            return 0.0
        phrase_length_bonus = len(kw.split()) * 0.8
        idf = self._idf_weights.get(kw.lower(), 1.0)
        tf = math.log(1 + matches)
        return tf * idf * phrase_length_bonus

    def classify(
        self, text_corpus: str, threshold: float = 0.3
    ) -> List[Tuple[str, str, float]]:
        """
        Classify text into UNILAG faculty/department buckets.

        Args:
            text_corpus: Combined text (title + abstract + keywords)
            threshold: Minimum score to include in results

        Returns:
            Sorted list of (faculty, department, score) tuples, best first.
        """
        if not text_corpus:
            return []

        try:
            text_lower = str(text_corpus).lower()
        except Exception:
            return []

        results = []

        for faculty, departments in self.structure.items():
            for dept, keywords in departments.items():
                total_score = 0.0
                matched_kws = []

                for kw in keywords:
                    try:
                        pattern = rf"\b{re.escape(kw)}\b"
                        found = re.findall(pattern, text_lower, re.IGNORECASE)
                        count = len(found)
                        if count > 0:
                            score = self._score_keyword(kw, count)
                            total_score += score
                            matched_kws.append((kw, count, round(score, 3)))
                    except Exception:
                        continue

                if total_score >= threshold:
                    results.append((faculty, dept, round(total_score, 3)))

        results.sort(key=lambda x: x[2], reverse=True)
        return results

    def classify_with_explanation(
        self, text_corpus: str, threshold: float = 0.3, top_n: int = 5
    ) -> Dict[str, Any]:
        """
        Returns classification results WITH full explanation of scoring.

        Returns:
            {
              'best_faculty': str,
              'best_department': str,
              'confidence': float,
              'results': [(faculty, dept, score), ...],
              'matched_keywords': [(keyword, count, score), ...],
              'sdg_alignment': [{'sdg': str, 'score': float, 'matched': [str]}, ...],
              'explanation': str
            }
        """
        if not text_corpus:
            return self._empty_explanation()

        try:
            text_lower = str(text_corpus).lower()
        except Exception:
            return self._empty_explanation()

        # Step 1: Full classification with keyword tracking
        all_results = []
        all_keyword_hits: Dict[str, Dict] = (
            {}
        )  # (faculty, dept) -> {kw: (count, score)}

        for faculty, departments in self.structure.items():
            for dept, keywords in departments.items():
                total_score = 0.0
                kw_details = []

                for kw in keywords:
                    try:
                        pattern = rf"\b{re.escape(kw)}\b"
                        found = re.findall(pattern, text_lower, re.IGNORECASE)
                        count = len(found)
                        if count > 0:
                            score = self._score_keyword(kw, count)
                            total_score += score
                            kw_details.append(
                                {
                                    "keyword": kw,
                                    "count": count,
                                    "score": round(score, 3),
                                    "idf": round(
                                        self._idf_weights.get(kw.lower(), 1.0), 3
                                    ),
                                }
                            )
                    except Exception:
                        continue

                if total_score >= threshold:
                    all_results.append(
                        {
                            "faculty": faculty,
                            "department": dept,
                            "score": round(total_score, 3),
                            "keywords": sorted(kw_details, key=lambda x: -x["score"]),
                        }
                    )

        all_results.sort(key=lambda x: -x["score"])
        top_results = all_results[:top_n]

        # Step 2: SDG alignment
        sdg_hits = self.detect_sdg_alignment(text_corpus)

        # Step 3: Build explanation
        if top_results:
            best = top_results[0]
            explanation = (
                f"Best match: {best['department']} ({best['faculty']}) "
                f"with score {best['score']:.2f}. "
                f"Top keywords: {', '.join(k['keyword'] for k in best['keywords'][:3])}."
            )
            if sdg_hits:
                explanation += f" Aligned with {sdg_hits[0]['sdg']}."
        else:
            explanation = "No strong faculty/department match found."

        return {
            "best_faculty": top_results[0]["faculty"] if top_results else None,
            "best_department": top_results[0]["department"] if top_results else None,
            "confidence": top_results[0]["score"] if top_results else 0.0,
            "results": [
                (r["faculty"], r["department"], r["score"]) for r in top_results
            ],
            "top_keywords": top_results[0]["keywords"][:5] if top_results else [],
            "sdg_alignment": sdg_hits[:3],
            "explanation": explanation,
            "all_matches": top_results,
        }

    def _empty_explanation(self) -> Dict[str, Any]:
        return {
            "best_faculty": None,
            "best_department": None,
            "confidence": 0.0,
            "results": [],
            "top_keywords": [],
            "sdg_alignment": [],
            "explanation": "No text provided.",
            "all_matches": [],
        }

    def detect_sdg_alignment(self, text_corpus: str) -> List[Dict[str, Any]]:
        """
        Detect which UN Sustainable Development Goals this paper aligns with.

        Returns:
            List of {'sdg': str, 'score': float, 'matched_keywords': [str]}
            sorted by score descending.
        """
        if not text_corpus:
            return []

        try:
            text_lower = str(text_corpus).lower()
        except Exception:
            return []

        sdg_results = []
        for sdg_name, keywords in SDG_MAP.items():
            matched = []
            score = 0.0
            for kw in keywords:
                try:
                    pattern = rf"\b{re.escape(kw)}\b"
                    found = re.findall(pattern, text_lower, re.IGNORECASE)
                    if found:
                        count = len(found)
                        # Simple scoring: longer keywords worth more
                        kw_score = count * len(kw.split()) * 0.5
                        score += kw_score
                        matched.append(kw)
                except Exception:
                    continue

            if score > 0:
                sdg_results.append(
                    {
                        "sdg": sdg_name,
                        "score": round(score, 2),
                        "matched_keywords": matched[:5],
                    }
                )

        sdg_results.sort(key=lambda x: -x["score"])
        return sdg_results

    def get_best_classification(
        self, text_corpus: str
    ) -> Optional[Tuple[str, str, float]]:
        """Returns the single best classification or None if no match."""
        try:
            results = self.classify(text_corpus)
            return results[0] if results else None
        except Exception:
            return None

    def get_keyword_density(self, text_corpus: str) -> List[Dict[str, Any]]:
        """
        Extract top meaningful keywords from a text corpus using TF scoring.
        Includes multi-word domain phrase detection with score boosts.
        Used for the keyword cloud endpoint.

        Returns list of {'word': str, 'count': int, 'score': float}
        """
        if not text_corpus:
            return []

        STOP_WORDS = {
            "the",
            "and",
            "for",
            "with",
            "this",
            "that",
            "from",
            "have",
            "been",
            "were",
            "their",
            "which",
            "these",
            "about",
            "other",
            "into",
            "than",
            "more",
            "such",
            "some",
            "what",
            "when",
            "where",
            "there",
            "also",
            "using",
            "used",
            "show",
            "study",
            "paper",
            "research",
            "result",
            "analysis",
            "based",
            "present",
            "data",
            "method",
            "effect",
            "approach",
            "review",
            "found",
            "between",
            "different",
            "however",
            "while",
            "both",
            "each",
            "thus",
            "among",
            "within",
            "during",
            "after",
            "before",
            "under",
            "very",
            "most",
            "only",
            "just",
            "they",
            "them",
        }

        try:
            text_lower = str(text_corpus).lower()
            words = re.findall(r"\b[a-z]{4,}\b", text_lower)
            counts: Dict[str, int] = {}
            for w in words:
                if w not in STOP_WORDS:
                    counts[w] = counts.get(w, 0) + 1

            # Multi-word phrase detection from known domain keywords
            phrase_counts: Dict[str, int] = {}
            phrase_parts: set = set()
            for kw in self._all_keywords:
                if " " in kw and len(kw) >= 8:
                    occ = len(re.findall(re.escape(kw), text_lower))
                    if occ > 0:
                        phrase_counts[kw] = occ
                        for part in kw.split():
                            if len(part) >= 4:
                                phrase_parts.add(part)

            # Build result - phrases first with 4x domain boost
            result = []
            for phrase, count in sorted(phrase_counts.items(), key=lambda x: -x[1])[
                :20
            ]:
                result.append(
                    {"word": phrase, "count": count, "score": round(count * 4.0, 2)}
                )

            # Add single words, skipping those covered by phrases
            for word, count in sorted(counts.items(), key=lambda x: -x[1]):
                if word in phrase_parts:
                    continue
                is_domain = word in self._all_keywords
                score = count * (2.5 if is_domain else 1.0)
                result.append({"word": word, "count": count, "score": round(score, 2)})

            result.sort(key=lambda x: -x["score"])
            return result[:60]
        except Exception:
            return []


# Singleton instance
classifier = UNILAGClassifier()
