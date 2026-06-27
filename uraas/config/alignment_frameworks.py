"""Alignment scoring taxonomy for continental and regional policy frameworks.

This module defines the canonical taxonomy used by the alignment engine to score
African research output against three families of policy frameworks:

  1. AU Charters (Banjul, Public Service, Cultural Renaissance, Malabo, Youth, ACDEG)
  2. AU Agenda 2063 (the seven aspirations, with their numbered goals)
  3. Regional bloc strategies (ECOWAS Vision 2050, SADC RISDP 2020-2030, EAC Vision 2050)

Each framework is decomposed into thematic pillars. A pillar carries two layers:

  - ``description``: 2-3 sentences of prose written in the vocabulary of African
    academic paper abstracts. These descriptions are embedded by a Model2Vec
    sentence-embedding model and compared with paper abstracts via cosine
    similarity to produce the semantic component of the alignment score.
  - ``keywords``: a curated term list that forms the auditable evidence layer.
    Keyword hits in titles/abstracts are surfaced to users as transparent
    justification for why a paper was mapped to a pillar.

Plain dicts only — this module must stay import-light and serialisable.
"""

ALIGNMENT_VERSION = 1

# Minimum pillar coverage (percent) below which a framework pillar is flagged
# as a research gap for an institution or country.
GAP_THRESHOLD = 25

FRAMEWORKS = {
    # ------------------------------------------------------------------
    # AU Charters
    # ------------------------------------------------------------------
    "banjul": {
        "name": "African Charter on Human and Peoples' Rights (Banjul Charter)",
        "type": "au_charter",
        "year": 1981,
        "color": "#1d4ed8",  # blue
        "pillars": {
            "civil_political_rights": {
                "name": "Civil and Political Rights",
                "description": (
                    "Research addressing civil liberties, political participation, due "
                    "process, freedom of expression and assembly in African states. "
                    "Includes studies of fair trial rights, arbitrary detention, press "
                    "freedom, torture prevention and the rule of law. Examines how "
                    "constitutions, courts and security agencies protect or violate "
                    "fundamental freedoms."
                ),
                "keywords": [
                    "human rights", "civil liberties", "freedom of expression",
                    "press freedom", "fair trial", "rule of law",
                    "arbitrary detention", "torture", "freedom of association",
                    "political rights", "right to life", "due process",
                    "fundamental freedoms",
                ],
            },
            "socioeconomic_cultural_rights": {
                "name": "Socio-economic and Cultural Rights",
                "description": (
                    "Studies of the right to health, education, work, housing and "
                    "social protection in African countries. Covers access to "
                    "healthcare and schooling, labour rights, decent working "
                    "conditions and social justice for poor and marginalised "
                    "populations. Includes analyses of state obligations to "
                    "progressively realise socio-economic and cultural rights."
                ),
                "keywords": [
                    "right to health", "right to education", "socio-economic rights",
                    "social protection", "labour rights", "right to work",
                    "housing rights", "cultural rights", "social justice",
                    "access to healthcare", "educational access",
                ],
            },
            "peoples_collective_rights": {
                "name": "Peoples' and Collective Rights",
                "description": (
                    "Research on collective and peoples' rights, including "
                    "self-determination, the right to development and sovereignty "
                    "over natural resources. Covers environmental rights and "
                    "environmental justice, land rights, community rights and the "
                    "claims of indigenous peoples. Includes studies of resource "
                    "governance, extractive industries and communities affected by "
                    "mining, oil and land dispossession."
                ),
                "keywords": [
                    "self-determination", "right to development", "collective rights",
                    "environmental rights", "indigenous peoples",
                    "natural resource sovereignty", "peoples' rights",
                    "right to peace", "land rights", "community rights",
                    "environmental justice", "resource governance",
                ],
            },
            "vulnerable_groups_protection": {
                "name": "Protection of Vulnerable Groups",
                "description": (
                    "Research on the rights and protection of women, children, "
                    "persons with disabilities, older persons, refugees and "
                    "internally displaced persons in Africa. Covers gender "
                    "discrimination, gender-based violence, child labour, human "
                    "trafficking and minority rights. Includes studies of social "
                    "inclusion and legal frameworks safeguarding vulnerable and "
                    "marginalised populations."
                ),
                "keywords": [
                    "women's rights", "child protection", "disability rights",
                    "rights of older persons", "gender discrimination",
                    "child labour", "human trafficking", "refugee rights",
                    "internally displaced persons", "minority rights",
                    "gender-based violence", "social inclusion",
                ],
            },
            "african_human_rights_system": {
                "name": "African Human Rights System",
                "description": (
                    "Scholarship on the institutions and procedures of the African "
                    "human rights system, including the African Commission and the "
                    "African Court on Human and Peoples' Rights. Examines human "
                    "rights litigation, jurisprudence, state reporting, treaty "
                    "compliance and domestication of regional instruments. Includes "
                    "studies of transitional justice and accountability mechanisms "
                    "for past violations."
                ),
                "keywords": [
                    "African Commission on Human and Peoples' Rights",
                    "African Court", "human rights litigation", "treaty compliance",
                    "state reporting", "regional human rights mechanisms",
                    "human rights jurisprudence", "domestication of treaties",
                    "transitional justice", "accountability",
                ],
            },
        },
    },
    "public_service": {
        "name": (
            "African Charter on Values and Principles of Public Service "
            "and Administration"
        ),
        "type": "au_charter",
        "year": 2011,
        "color": "#0f766e",  # teal
        "pillars": {
            "service_delivery": {
                "name": "Public Service Delivery",
                "description": (
                    "Research on the quality, efficiency and equity of public "
                    "service delivery in African countries. Covers citizen "
                    "satisfaction, local government services, public utilities and "
                    "public sector performance management. Includes studies of "
                    "service delivery innovation and administrative reforms aimed "
                    "at improving outcomes for citizens."
                ),
                "keywords": [
                    "public service delivery", "service quality",
                    "citizen satisfaction", "local government services",
                    "public sector performance", "service delivery innovation",
                    "public utilities", "administrative efficiency",
                    "performance management",
                ],
            },
            "ethics_anticorruption": {
                "name": "Ethics and Anti-corruption",
                "description": (
                    "Studies of corruption, bribery and integrity in the African "
                    "public sector. Covers anti-corruption agencies and reforms, "
                    "procurement fraud, illicit enrichment, conflict of interest, "
                    "asset declaration and whistleblowing. Includes research on "
                    "public sector ethics, codes of conduct, accountability and "
                    "citizens' trust in government."
                ),
                "keywords": [
                    "corruption", "anti-corruption", "public sector ethics",
                    "accountability", "integrity", "bribery",
                    "conflict of interest", "asset declaration", "whistleblowing",
                    "procurement fraud", "illicit enrichment", "code of conduct",
                    "public trust",
                ],
            },
            "transparency_access_to_information": {
                "name": "Transparency and Access to Information",
                "description": (
                    "Research on access to information, freedom of information laws "
                    "and open government in Africa. Covers transparency in public "
                    "budgets and fiscal management, open data initiatives and "
                    "disclosure of public records. Includes studies of the right to "
                    "information as a tool for accountability and citizen oversight."
                ),
                "keywords": [
                    "access to information", "freedom of information",
                    "open government", "transparency", "open data",
                    "fiscal transparency", "budget transparency", "public records",
                    "right to information", "information disclosure",
                ],
            },
            "egovernment_modernisation": {
                "name": "E-government and Administrative Modernisation",
                "description": (
                    "Research on e-government, digital government and the digital "
                    "transformation of public administration in Africa. Covers "
                    "digital public services, digital identity systems, civil "
                    "service and bureaucratic reform, and administrative "
                    "modernisation programmes. Includes studies of e-governance "
                    "adoption, implementation challenges and impacts on service "
                    "delivery."
                ),
                "keywords": [
                    "e-government", "digital government", "digital public services",
                    "civil service reform", "public administration reform",
                    "digital identity", "administrative modernisation",
                    "bureaucratic reform", "digital transformation of government",
                    "e-governance",
                ],
            },
            "civil_service_hrm": {
                "name": "Civil Service and Human Resource Management",
                "description": (
                    "Studies of civil service systems, public sector employment and "
                    "human resource management in African states. Covers "
                    "meritocracy, recruitment, training and capacity building of "
                    "public officials, motivation and working conditions of public "
                    "servants. Includes research on decentralisation and the "
                    "staffing and management of local governance structures."
                ),
                "keywords": [
                    "civil service", "public servants",
                    "human resource management", "public sector employment",
                    "meritocracy", "capacity building",
                    "training of public officials", "public sector motivation",
                    "working conditions", "decentralisation", "local governance",
                ],
            },
        },
    },
    "cultural_renaissance": {
        "name": "Charter for African Cultural Renaissance",
        "type": "au_charter",
        "year": 2006,
        "color": "#b45309",  # amber
        "pillars": {
            "heritage_preservation_restitution": {
                "name": "Heritage Preservation and Restitution",
                "description": (
                    "Research on the preservation, conservation and digitisation of "
                    "African cultural heritage, including museums, archives, "
                    "monuments and world heritage sites. Covers archaeology and "
                    "heritage management as well as the restitution and "
                    "repatriation of cultural property and looted artefacts. "
                    "Includes debates on ownership, custodianship and access to "
                    "African cultural objects."
                ),
                "keywords": [
                    "cultural heritage", "heritage preservation", "museums",
                    "archives", "restitution of cultural property",
                    "repatriation of artefacts", "world heritage sites",
                    "monuments", "archaeology", "heritage conservation",
                    "digitisation of heritage", "cultural property",
                ],
            },
            "african_languages": {
                "name": "African Languages",
                "description": (
                    "Linguistic research on African and indigenous languages, "
                    "including documentation of endangered languages, orthography "
                    "development, sociolinguistics and translation. Covers language "
                    "policy, mother tongue education and multilingualism in African "
                    "classrooms and societies. Includes studies of major languages "
                    "such as Yoruba, Swahili, Hausa and Igbo."
                ),
                "keywords": [
                    "African languages", "indigenous languages", "language policy",
                    "mother tongue education", "multilingualism", "linguistics",
                    "language documentation", "endangered languages", "Yoruba",
                    "Swahili", "Hausa", "Igbo", "orthography", "sociolinguistics",
                    "translation",
                ],
            },
            "creative_cultural_industries": {
                "name": "Creative and Cultural Industries",
                "description": (
                    "Research on Africa's creative economy and cultural industries, "
                    "including film, music, literature, publishing, performing and "
                    "visual arts. Covers Nollywood and African cinema, festivals, "
                    "cultural tourism and cultural entrepreneurship. Includes "
                    "studies of the economic contribution, value chains and policy "
                    "environment of the creative sector."
                ),
                "keywords": [
                    "creative industries", "creative economy", "Nollywood",
                    "African cinema", "African music", "performing arts",
                    "visual arts", "cultural entrepreneurship", "film industry",
                    "literature", "publishing", "festivals", "cultural tourism",
                ],
            },
            "identity_diversity": {
                "name": "Cultural Identity and Diversity",
                "description": (
                    "Scholarship on African and cultural identity, pan-Africanism, "
                    "afrocentricity and cultural diversity. Covers oral tradition, "
                    "folklore, ethnicity, religion and cultural values, and "
                    "intercultural dialogue within and between African societies. "
                    "Includes studies of decolonisation of culture, thought and "
                    "representation."
                ),
                "keywords": [
                    "cultural identity", "African identity", "pan-Africanism",
                    "cultural diversity", "intercultural dialogue",
                    "decolonisation", "afrocentricity", "oral tradition",
                    "folklore", "ethnicity", "religion and culture",
                    "cultural values",
                ],
            },
            "indigenous_knowledge_systems": {
                "name": "Indigenous Knowledge Systems",
                "description": (
                    "Research on indigenous, traditional and endogenous knowledge "
                    "systems in Africa, including traditional medicine, "
                    "ethnobotany, ethnomedicine and traditional ecological "
                    "knowledge. Covers the documentation, validation and protection "
                    "of traditional knowledge and cultural expressions. Includes "
                    "debates on knowledge sovereignty, biopiracy and benefit "
                    "sharing."
                ),
                "keywords": [
                    "indigenous knowledge", "traditional knowledge",
                    "endogenous knowledge", "traditional medicine", "ethnobotany",
                    "ethnomedicine", "indigenous knowledge systems",
                    "traditional ecological knowledge", "knowledge sovereignty",
                    "biopiracy", "traditional cultural expressions",
                ],
            },
            "diaspora_historical_memory": {
                "name": "Diaspora and Historical Memory",
                "description": (
                    "Historical research on the African diaspora, the slave trade, "
                    "colonialism and their post-colonial legacies. Covers African "
                    "history, oral history, memory studies and the politics of "
                    "historical memory and reparations. Includes scholarship on the "
                    "African renaissance and connections between the continent and "
                    "its diaspora."
                ),
                "keywords": [
                    "African diaspora", "slave trade", "historical memory",
                    "colonialism", "post-colonial", "African history",
                    "oral history", "memory studies", "reparations",
                    "African renaissance",
                ],
            },
        },
    },
    "malabo": {
        "name": (
            "AU Convention on Cyber Security and Personal Data Protection "
            "(Malabo Convention)"
        ),
        "type": "au_charter",
        "year": 2014,
        "color": "#6d28d9",  # violet
        "pillars": {
            "electronic_transactions": {
                "name": "Electronic Transactions and Digital Economy",
                "description": (
                    "Research on e-commerce, electronic transactions and the "
                    "digital economy in Africa. Covers digital payments, mobile "
                    "money, fintech, digital financial services and online "
                    "marketplaces. Includes studies of electronic contracts, "
                    "electronic signatures, payment systems and the regulation of "
                    "digital trade."
                ),
                "keywords": [
                    "e-commerce", "electronic transactions", "digital payments",
                    "mobile money", "electronic contracts", "digital trade",
                    "fintech", "online marketplaces", "electronic signatures",
                    "digital economy", "payment systems",
                    "digital financial services",
                ],
            },
            "data_protection_privacy": {
                "name": "Data Protection and Privacy",
                "description": (
                    "Studies of personal data protection, privacy law and data "
                    "governance in African countries. Covers data protection "
                    "authorities, consent, biometric data, cross-border data flows, "
                    "data sovereignty and data localisation. Includes analyses of "
                    "compliance with privacy frameworks and protection of "
                    "information privacy in digital systems."
                ),
                "keywords": [
                    "data protection", "personal data", "privacy", "data privacy",
                    "data protection authority", "consent", "data governance",
                    "cross-border data flows", "data sovereignty",
                    "data localisation", "privacy law", "information privacy",
                    "biometric data",
                ],
            },
            "cybersecurity": {
                "name": "Cybersecurity",
                "description": (
                    "Research on cybersecurity, network and information security in "
                    "African contexts. Covers protection of critical "
                    "infrastructure, cyber resilience, cyber threats, malware, "
                    "intrusion detection, encryption and vulnerability assessment. "
                    "Includes studies of national cybersecurity strategies, "
                    "capacity and incident response."
                ),
                "keywords": [
                    "cybersecurity", "cyber security", "network security",
                    "information security", "critical infrastructure protection",
                    "cyber resilience", "cyber threats", "malware",
                    "intrusion detection", "encryption",
                    "vulnerability assessment",
                ],
            },
            "cybercrime": {
                "name": "Cybercrime",
                "description": (
                    "Research on cybercrime and online criminality in Africa, "
                    "including computer fraud, phishing, identity theft, hacking "
                    "and ransomware. Covers cybercrime legislation, digital "
                    "forensics, electronic evidence and law enforcement responses "
                    "to internet fraud. Includes criminological studies of online "
                    "fraud networks and victimisation."
                ),
                "keywords": [
                    "cybercrime", "computer fraud", "phishing", "online fraud",
                    "identity theft", "ransomware", "digital forensics",
                    "cybercrime legislation", "electronic evidence",
                    "internet fraud", "hacking",
                ],
            },
            "digital_rights_cooperation": {
                "name": "Digital Rights and Internet Governance",
                "description": (
                    "Scholarship on digital rights, internet governance and online "
                    "freedom of expression in Africa. Covers surveillance, internet "
                    "shutdowns, platform regulation, misinformation and digital "
                    "inclusion. Includes studies of internet policy and the balance "
                    "between security, rights and access in digital spaces."
                ),
                "keywords": [
                    "digital rights", "internet governance",
                    "online freedom of expression", "surveillance",
                    "internet shutdowns", "digital inclusion", "internet policy",
                    "platform regulation", "misinformation",
                ],
            },
        },
    },
    "youth": {
        "name": "African Youth Charter",
        "type": "au_charter",
        "year": 2006,
        "color": "#15803d",  # green
        "pillars": {
            "education_skills": {
                "name": "Youth Education and Skills",
                "description": (
                    "Research on education and skills development for African "
                    "youth, including technical and vocational education and "
                    "training (TVET), tertiary education and STEM education. Covers "
                    "literacy, digital skills, curriculum reform, graduate "
                    "employability skills and access to education. Includes studies "
                    "of out-of-school youth and barriers to educational attainment."
                ),
                "keywords": [
                    "youth education", "technical and vocational education", "TVET",
                    "skills development", "tertiary education",
                    "out-of-school youth", "digital skills", "literacy",
                    "STEM education", "curriculum reform", "graduate skills",
                    "education access",
                ],
            },
            "employment_entrepreneurship": {
                "name": "Youth Employment and Entrepreneurship",
                "description": (
                    "Studies of youth employment, unemployment and livelihoods in "
                    "African labour markets. Covers entrepreneurship and youth-led "
                    "start-ups, self-employment, the informal sector, the gig "
                    "economy and small and medium enterprises. Includes research on "
                    "job creation, decent work and policies to absorb young people "
                    "into productive employment."
                ),
                "keywords": [
                    "youth employment", "youth unemployment", "entrepreneurship",
                    "youth entrepreneurship", "informal sector", "job creation",
                    "start-ups", "self-employment", "labour market", "decent work",
                    "gig economy", "small and medium enterprises", "livelihoods",
                ],
            },
            "youth_health_wellbeing": {
                "name": "Youth Health and Wellbeing",
                "description": (
                    "Research on adolescent and youth health in Africa, including "
                    "sexual and reproductive health, HIV/AIDS, teenage pregnancy "
                    "and adolescent nutrition. Covers substance and drug abuse, "
                    "mental health and access to youth-friendly health services. "
                    "Includes studies of risk behaviours and interventions "
                    "promoting young people's wellbeing."
                ),
                "keywords": [
                    "adolescent health", "youth health", "HIV/AIDS",
                    "sexual and reproductive health", "teenage pregnancy",
                    "substance abuse", "drug abuse", "mental health",
                    "adolescent nutrition", "youth-friendly services",
                ],
            },
            "participation_civic_engagement": {
                "name": "Youth Participation and Civic Engagement",
                "description": (
                    "Scholarship on youth participation in politics, governance and "
                    "civic life in Africa. Covers youth policy, youth leadership "
                    "and representation, student activism, social movements, "
                    "volunteerism and digital activism. Includes studies of how "
                    "young people engage with, contest and shape political "
                    "processes."
                ),
                "keywords": [
                    "youth participation", "civic engagement", "youth in politics",
                    "youth policy", "student activism", "youth leadership",
                    "youth representation", "social movements", "volunteerism",
                    "digital activism", "political participation",
                ],
            },
            "youth_peace_security": {
                "name": "Youth, Peace and Security",
                "description": (
                    "Research on young people in conflict and peacebuilding in "
                    "Africa, including youth radicalisation, violent extremism, "
                    "gangs, cultism and youth violence. Covers the roles of youth "
                    "in post-conflict recovery and the youth, peace and security "
                    "agenda. Includes studies of drivers of youth recruitment into "
                    "armed groups and programmes for reintegration."
                ),
                "keywords": [
                    "youth and conflict", "youth radicalisation",
                    "violent extremism", "youth in peacebuilding", "gangs",
                    "cultism", "youth violence", "post-conflict youth",
                    "youth peace and security",
                ],
            },
        },
    },
    "acdeg": {
        "name": "African Charter on Democracy, Elections and Governance (ACDEG)",
        "type": "au_charter",
        "year": 2007,
        "color": "#b91c1c",  # red
        "pillars": {
            "democracy_rule_of_law": {
                "name": "Democracy and Rule of Law",
                "description": (
                    "Research on democracy, democratisation and constitutionalism "
                    "in African states. Covers the rule of law, separation of "
                    "powers, judicial independence, constitutional reform, "
                    "political parties and civil society. Includes studies of "
                    "democratic consolidation, democratic backsliding, "
                    "authoritarianism and presidential term limits."
                ),
                "keywords": [
                    "democracy", "democratisation", "constitutionalism",
                    "rule of law", "separation of powers", "judicial independence",
                    "constitutional reform", "civil society", "political parties",
                    "democratic consolidation", "authoritarianism", "term limits",
                    "democratic backsliding",
                ],
            },
            "elections": {
                "name": "Elections and Electoral Integrity",
                "description": (
                    "Studies of elections and electoral processes in Africa, "
                    "including electoral commissions, voter registration, biometric "
                    "voter technologies and election observation. Covers electoral "
                    "violence, electoral reform, election petitions, campaign "
                    "finance and voter turnout. Includes research on the conduct "
                    "and integrity of free and fair elections."
                ),
                "keywords": [
                    "elections", "electoral commission", "election observation",
                    "voter registration", "electoral violence",
                    "free and fair elections", "electoral reform", "voter turnout",
                    "election petition", "biometric voter", "electoral integrity",
                    "campaign finance",
                ],
            },
            "unconstitutional_change": {
                "name": "Unconstitutional Changes of Government",
                "description": (
                    "Research on coups d'etat, military rule and unconstitutional "
                    "changes of government in Africa. Covers civil-military "
                    "relations, juntas, political transitions, power transfers and "
                    "third-term bids that subvert constitutional order. Includes "
                    "studies of regional and continental responses to military "
                    "takeovers."
                ),
                "keywords": [
                    "coup d'etat", "military coup",
                    "unconstitutional change of government", "military rule",
                    "civil-military relations", "junta", "political transition",
                    "power transfer", "third-term bids",
                ],
            },
            "governance_institutions": {
                "name": "Governance and Public Institutions",
                "description": (
                    "Scholarship on good governance and the performance of public "
                    "institutions in Africa. Covers anti-corruption, "
                    "accountability, transparency, the African Peer Review "
                    "Mechanism, decentralisation and local government. Includes "
                    "studies of state capacity, institutional reform and political "
                    "leadership."
                ),
                "keywords": [
                    "good governance", "governance", "anti-corruption",
                    "accountability", "African Peer Review Mechanism",
                    "public institutions", "decentralisation", "local government",
                    "state capacity", "institutional reform", "transparency",
                    "leadership",
                ],
            },
            "participation_gender_equity": {
                "name": "Participation, Gender and Equity",
                "description": (
                    "Research on political participation and inclusive governance "
                    "in Africa, with emphasis on women in politics, gender quotas "
                    "and women's political leadership. Covers citizen "
                    "participation, participatory democracy, civic education and "
                    "the representation of marginalised groups. Includes studies of "
                    "barriers to and strategies for equitable political inclusion."
                ),
                "keywords": [
                    "political participation", "women in politics", "gender quota",
                    "citizen participation", "inclusive governance",
                    "marginalised groups", "representation",
                    "women's political leadership", "participatory democracy",
                    "civic education",
                ],
            },
        },
    },
    # ------------------------------------------------------------------
    # Agenda 2063
    # ------------------------------------------------------------------
    "agenda2063": {
        "name": "AU Agenda 2063: The Africa We Want",
        "type": "agenda2063",
        "year": 2013,
        "color": "#047857",  # emerald green
        "pillars": {
            "aspiration_1_prosperity": {
                "name": (
                    "A Prosperous Africa (Inclusive Growth & Sustainable "
                    "Development)"
                ),
                "goals": [1, 2, 3, 4, 5, 6, 7],
                "description": (
                    "Research on poverty reduction, inclusive growth and "
                    "sustainable development in Africa. Covers food security and "
                    "agricultural productivity, public health including maternal "
                    "health and infectious diseases such as malaria, education "
                    "quality, nutrition and social protection. Includes studies of "
                    "renewable energy, climate change adaptation, water security, "
                    "the blue economy, industrialisation and economic "
                    "diversification."
                ),
                "keywords": [
                    "poverty reduction", "inclusive growth",
                    "sustainable development", "food security",
                    "agricultural productivity", "climate-smart agriculture",
                    "public health", "maternal health", "infectious diseases",
                    "malaria", "education quality", "STEM education",
                    "renewable energy", "climate change adaptation",
                    "water security", "blue economy", "industrialisation",
                    "economic diversification", "social protection", "nutrition",
                    "universal health coverage",
                ],
            },
            "aspiration_2_integration": {
                "name": (
                    "An Integrated Continent (Pan-Africanism & African "
                    "Renaissance)"
                ),
                "goals": [8, 9, 10],
                "description": (
                    "Studies of continental and regional integration in Africa, "
                    "including the African Continental Free Trade Area (AfCFTA), "
                    "intra-African trade, customs unions and regional value "
                    "chains. Covers free movement of persons, the African passport, "
                    "monetary union and cross-border trade. Includes research on "
                    "infrastructure development, transport corridors and regional "
                    "connectivity in the spirit of pan-Africanism."
                ),
                "keywords": [
                    "regional integration", "African Continental Free Trade Area",
                    "AfCFTA", "intra-African trade", "free movement of persons",
                    "African passport", "monetary union",
                    "infrastructure development", "transport corridors",
                    "regional connectivity", "cross-border trade",
                    "pan-Africanism", "customs union", "regional value chains",
                ],
            },
            "aspiration_3_governance": {
                "name": "Good Governance, Democracy & Human Rights",
                "description": (
                    "Research on good governance, democracy, justice and human "
                    "rights across African states. Covers the rule of law, "
                    "anti-corruption, accountability, transparency and elections. "
                    "Includes studies of judicial reform, institutional capacity, "
                    "decentralisation and civic participation in democratic "
                    "governance."
                ),
                "goals": [11, 12],
                "keywords": [
                    "good governance", "democracy", "human rights", "rule of law",
                    "justice", "anti-corruption", "accountability", "elections",
                    "judicial reform", "institutional capacity", "transparency",
                    "decentralisation", "civic participation",
                ],
            },
            "aspiration_4_peace_security": {
                "name": "A Peaceful and Secure Africa",
                "goals": [13, 14, 15],
                "description": (
                    "Research on peace, security and conflict in Africa, including "
                    "armed conflict, terrorism, violent extremism, insurgency and "
                    "communal and farmer-herder conflicts. Covers peacebuilding, "
                    "conflict resolution, mediation, peacekeeping and post-conflict "
                    "reconstruction. Includes studies of security sector reform, "
                    "proliferation of small arms and human security."
                ),
                "keywords": [
                    "peacebuilding", "conflict resolution", "armed conflict",
                    "terrorism", "violent extremism", "insurgency", "peacekeeping",
                    "security sector reform", "mediation",
                    "post-conflict reconstruction", "small arms",
                    "communal conflict", "farmer-herder conflict",
                    "human security",
                ],
            },
            "aspiration_5_culture": {
                "name": "Strong Cultural Identity & Shared Values",
                "goals": [16],
                "description": (
                    "Scholarship on African cultural identity, heritage and shared "
                    "values, including African languages, oral tradition and "
                    "indigenous knowledge. Covers the creative industries, arts and "
                    "culture, museums, heritage conservation and the cultural "
                    "economy. Includes studies of the African renaissance, "
                    "decolonising knowledge and African philosophy."
                ),
                "keywords": [
                    "cultural identity", "cultural heritage", "African languages",
                    "creative industries", "African renaissance",
                    "indigenous knowledge", "oral tradition", "African values",
                    "arts and culture", "heritage conservation",
                    "cultural economy", "museums", "decolonising knowledge",
                    "African philosophy",
                ],
            },
            "aspiration_6_people_driven": {
                "name": "People-Driven Development (Women & Youth)",
                "goals": [17, 18],
                "description": (
                    "Research on gender equality, women's empowerment and youth "
                    "development in Africa. Covers gender-based violence, female "
                    "genital mutilation, child marriage, girls' education, women in "
                    "leadership and women in STEM. Includes studies of youth "
                    "employment and entrepreneurship, child welfare and protection, "
                    "gender mainstreaming and harnessing the demographic dividend."
                ),
                "keywords": [
                    "gender equality", "women empowerment",
                    "gender-based violence", "women in leadership",
                    "girls' education", "youth empowerment", "youth employment",
                    "child welfare", "child protection",
                    "female genital mutilation", "child marriage",
                    "women in STEM", "youth entrepreneurship",
                    "demographic dividend", "gender mainstreaming",
                ],
            },
            "aspiration_7_global_player": {
                "name": "Africa as a Strong Global Player",
                "goals": [19, 20],
                "description": (
                    "Research on Africa's place in the global economy and global "
                    "governance, including South-South cooperation and "
                    "international partnerships. Covers development finance, "
                    "domestic resource mobilisation, illicit financial flows, debt "
                    "sustainability and tax reform. Includes studies of foreign "
                    "direct investment, capital markets, remittances and "
                    "development assistance."
                ),
                "keywords": [
                    "global governance", "South-South cooperation",
                    "development finance", "domestic resource mobilisation",
                    "illicit financial flows", "capital markets",
                    "foreign direct investment", "debt sustainability",
                    "international partnerships", "tax reform", "remittances",
                    "development assistance",
                ],
            },
        },
    },
    # ------------------------------------------------------------------
    # Regional blocs
    # ------------------------------------------------------------------
    "ecowas": {
        "name": "ECOWAS Vision 2050 (West Africa)",
        "type": "regional_bloc",
        "year": 2022,
        "color": "#0369a1",  # sky blue
        "pillars": {
            "trade_free_movement": {
                "name": "Trade and Free Movement",
                "description": (
                    "Research on trade integration and free movement in West "
                    "Africa, including the ECOWAS Trade Liberalisation Scheme, "
                    "common external tariff, rules of origin and trade "
                    "facilitation. Covers intra-regional and informal cross-border "
                    "trade and customs administration. Includes studies of monetary "
                    "integration, the West African Monetary Zone and the proposed "
                    "ECO single currency."
                ),
                "keywords": [
                    "ECOWAS Trade Liberalisation Scheme", "intra-regional trade",
                    "free movement of persons", "common external tariff",
                    "rules of origin", "informal cross-border trade",
                    "ECO currency", "monetary integration",
                    "West African Monetary Zone", "customs", "trade facilitation",
                ],
            },
            "agriculture_ecowap": {
                "name": "Agriculture and Food Security (ECOWAP)",
                "description": (
                    "Studies of agriculture and food security in West Africa under "
                    "ECOWAP and CAADP regional agricultural policies. Covers "
                    "smallholder farmers, agricultural transformation, food "
                    "sovereignty, agro-pastoralism, irrigation and fertiliser "
                    "policy. Includes research on key value chains such as rice and "
                    "cocoa."
                ),
                "keywords": [
                    "ECOWAP", "regional agricultural policy",
                    "food security West Africa", "CAADP", "rice value chain",
                    "cocoa", "smallholder farmers", "agricultural transformation",
                    "food sovereignty", "agro-pastoralism", "irrigation",
                    "fertiliser policy",
                ],
            },
            "energy_wapp": {
                "name": "Energy and the West African Power Pool",
                "description": (
                    "Research on energy access and power systems in West Africa, "
                    "including the West African Power Pool, regional electricity "
                    "markets and cross-border power interconnection. Covers rural "
                    "electrification, energy poverty, off-grid solar and renewable "
                    "energy deployment. Includes studies of the West African Gas "
                    "Pipeline and regional energy infrastructure."
                ),
                "keywords": [
                    "West African Power Pool", "regional electricity market",
                    "energy access", "rural electrification",
                    "renewable energy West Africa", "solar power",
                    "West African Gas Pipeline", "power interconnection",
                    "energy poverty", "off-grid solar",
                ],
            },
            "peace_security_governance": {
                "name": "Peace, Security and Governance",
                "description": (
                    "Research on peace, security and democratic governance in West "
                    "Africa and the Sahel, including jihadist insurgency, "
                    "counter-terrorism and recent coups. Covers ECOWAS conflict "
                    "prevention, ECOMOG interventions, early warning systems and "
                    "the regional security architecture. Includes studies of "
                    "democratic governance and political instability in the "
                    "subregion."
                ),
                "keywords": [
                    "ECOWAS conflict prevention", "ECOMOG", "Sahel security",
                    "coup West Africa", "jihadist insurgency",
                    "regional security architecture", "early warning systems",
                    "democratic governance West Africa", "counter-terrorism",
                ],
            },
            "health_waho": {
                "name": "Regional Health (WAHO)",
                "description": (
                    "Research on regional health systems and epidemic preparedness "
                    "in West Africa, coordinated through the West African Health "
                    "Organisation. Covers disease surveillance and pandemic "
                    "response, including outbreaks of Ebola and Lassa fever. "
                    "Includes studies of pharmaceutical regulation and One Health "
                    "approaches linking human, animal and environmental health."
                ),
                "keywords": [
                    "West African Health Organisation", "epidemic preparedness",
                    "Ebola", "Lassa fever", "regional health systems",
                    "disease surveillance", "pandemic response West Africa",
                    "pharmaceutical regulation", "One Health",
                ],
            },
        },
    },
    "sadc": {
        "name": (
            "SADC Regional Indicative Strategic Development Plan 2020-2030 "
            "(Southern Africa)"
        ),
        "type": "regional_bloc",
        "year": 2020,
        "color": "#4338ca",  # indigo violet
        "pillars": {
            "industrial_development_market_integration": {
                "name": "Industrial Development and Market Integration",
                "description": (
                    "Research on industrialisation and market integration in "
                    "Southern Africa, including regional value chains, "
                    "agro-processing, mineral beneficiation and pharmaceutical "
                    "manufacturing. Covers the SADC free trade area, macroeconomic "
                    "convergence, financial integration and manufacturing "
                    "competitiveness. Includes studies of the green economy, blue "
                    "economy and tourism development."
                ),
                "keywords": [
                    "SADC industrialisation", "regional value chains",
                    "agro-processing", "mineral beneficiation",
                    "pharmaceutical manufacturing", "SADC free trade area",
                    "macroeconomic convergence", "financial integration",
                    "green economy", "blue economy",
                    "manufacturing competitiveness", "tourism development",
                ],
            },
            "infrastructure": {
                "name": "Regional Infrastructure",
                "description": (
                    "Studies of regional infrastructure in Southern Africa, "
                    "including the Southern African Power Pool, transport "
                    "corridors, railways and port infrastructure. Covers energy "
                    "security, renewable energy, transboundary water resources and "
                    "ICT connectivity. Includes research on broadband access and "
                    "infrastructure financing for regional development."
                ),
                "keywords": [
                    "Southern African Power Pool", "transport corridors",
                    "regional infrastructure", "ICT connectivity",
                    "transboundary water", "energy security",
                    "renewable energy Southern Africa", "railway development",
                    "port infrastructure", "broadband access",
                ],
            },
            "social_human_capital": {
                "name": "Social and Human Capital Development",
                "description": (
                    "Research on health, education and human capital in Southern "
                    "Africa, including health systems strengthening, HIV/AIDS and "
                    "tuberculosis. Covers skills development, qualifications "
                    "frameworks, education quality, decent work and labour "
                    "migration. Includes studies of food and nutrition security and "
                    "social protection programmes."
                ),
                "keywords": [
                    "health systems strengthening", "HIV/AIDS Southern Africa",
                    "tuberculosis", "skills development",
                    "qualifications framework", "food and nutrition security",
                    "decent work", "labour migration", "education quality",
                    "social protection",
                ],
            },
            "peace_security_governance": {
                "name": "Peace, Security and Governance",
                "description": (
                    "Research on political stability, peace and governance in "
                    "Southern Africa, including SADC mediation and electoral "
                    "observation missions. Covers regional peacekeeping, conflict "
                    "prevention and the rule of law. Includes studies of democratic "
                    "governance and political dynamics in SADC member states."
                ),
                "keywords": [
                    "SADC mediation", "electoral observation SADC",
                    "political stability", "regional peacekeeping",
                    "governance Southern Africa", "conflict prevention",
                    "rule of law",
                ],
            },
            "climate_gender_youth": {
                "name": "Climate, Gender and Youth (Cross-cutting)",
                "description": (
                    "Research on cross-cutting development themes in Southern "
                    "Africa, including climate change, drought, El Nino effects, "
                    "cyclones and disaster risk management. Covers environmental "
                    "management and biodiversity conservation in the region. "
                    "Includes studies of gender mainstreaming and youth empowerment "
                    "in regional development."
                ),
                "keywords": [
                    "climate change Southern Africa", "drought", "El Nino",
                    "disaster risk management", "cyclone", "gender mainstreaming",
                    "youth empowerment", "environmental management",
                    "biodiversity",
                ],
            },
        },
    },
    "eac": {
        "name": "EAC Vision 2050 (East Africa)",
        "type": "regional_bloc",
        "year": 2015,
        "color": "#dc2626",  # red
        "pillars": {
            "common_market_integration": {
                "name": "Common Market and Integration",
                "description": (
                    "Research on East African economic and political integration, "
                    "including the EAC common market, customs union, single customs "
                    "territory and proposed monetary union and political "
                    "federation. Covers free movement of labour, non-tariff "
                    "barriers, harmonisation of standards and cross-border "
                    "investment. Includes studies of the progress and challenges of "
                    "regional integration in East Africa."
                ),
                "keywords": [
                    "EAC common market", "customs union",
                    "East African monetary union", "free movement of labour",
                    "non-tariff barriers", "single customs territory",
                    "regional integration East Africa", "political federation",
                    "harmonisation of standards", "cross-border investment",
                ],
            },
            "infrastructure": {
                "name": "Regional Infrastructure",
                "description": (
                    "Studies of transport, energy and ICT infrastructure in East "
                    "Africa, including the Northern and Central Corridors and the "
                    "standard gauge railway. Covers regional transport networks, "
                    "energy interconnection, one-stop border posts and ICT "
                    "infrastructure. Includes research on infrastructure financing "
                    "and the economics of regional connectivity."
                ),
                "keywords": [
                    "Northern Corridor", "Central Corridor",
                    "standard gauge railway", "regional transport",
                    "ICT infrastructure", "energy interconnection",
                    "infrastructure financing", "one-stop border posts",
                ],
            },
            "agriculture_food_security": {
                "name": "Agriculture and Food Security",
                "description": (
                    "Research on agriculture, the rural economy and food security "
                    "in East Africa. Covers smallholder productivity, agricultural "
                    "trade and key value chains including dairy, coffee, tea and "
                    "horticulture. Includes studies of food safety challenges such "
                    "as aflatoxin contamination."
                ),
                "keywords": [
                    "agriculture East Africa", "food security", "rural economy",
                    "dairy value chain", "coffee", "tea", "horticulture",
                    "smallholder productivity", "agricultural trade", "aflatoxin",
                ],
            },
            "industrialisation_trade_services": {
                "name": "Industrialisation, Trade and Services",
                "description": (
                    "Studies of industrialisation, manufacturing and services in "
                    "East Africa, including SME development, value addition and the "
                    "textile, leather and pharmaceutical industries. Covers "
                    "services trade and tourism in the region. Includes research on "
                    "industrial policy and competitiveness of East African firms."
                ),
                "keywords": [
                    "industrialisation East Africa", "manufacturing",
                    "SME development", "value addition", "tourism East Africa",
                    "services trade", "textile industry",
                    "pharmaceutical production", "leather value chain",
                ],
            },
            "natural_resources_environment": {
                "name": "Natural Resources and Environment",
                "description": (
                    "Research on natural resources and environmental management in "
                    "East Africa, including the Lake Victoria basin and "
                    "transboundary water management. Covers climate change, "
                    "forestry, wildlife conservation and biodiversity in the "
                    "region. Includes studies of the blue economy and sustainable "
                    "use of shared ecosystems."
                ),
                "keywords": [
                    "Lake Victoria basin", "transboundary water management",
                    "climate change East Africa", "forestry",
                    "wildlife conservation", "biodiversity",
                    "environmental management", "blue economy East Africa",
                ],
            },
        },
    },
}

FRAMEWORK_GROUPS = {
    "AU Charters": [
        "banjul", "public_service", "cultural_renaissance",
        "malabo", "youth", "acdeg",
    ],
    "Agenda 2063": ["agenda2063"],
    "Regional Blocs": ["ecowas", "sadc", "eac"],
}


def get_framework(key: str) -> dict | None:
    return FRAMEWORKS.get(key)


def all_framework_keys() -> list:
    return list(FRAMEWORKS)
