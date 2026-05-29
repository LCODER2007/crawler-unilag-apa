import json
import os

# Sub-regions and countries
subregions = {
    "North Africa": ["Egypt", "Morocco", "Algeria", "Tunisia", "Libya", "Sudan"],
    "West Africa": [
        "Nigeria",
        "Ghana",
        "Senegal",
        "Cote d'Ivoire",
        "Benin",
        "Burkina Faso",
        "Cape Verde",
        "Gambia",
        "Guinea",
        "Guinea-Bissau",
        "Liberia",
        "Mali",
        "Mauritania",
        "Niger",
        "Sierra Leone",
        "Togo",
    ],
    "East Africa": [
        "Kenya",
        "Uganda",
        "Tanzania",
        "Ethiopia",
        "Rwanda",
        "Burundi",
        "Djibouti",
        "Eritrea",
        "Somalia",
        "South Sudan",
        "Madagascar",
        "Mauritius",
        "Seychelles",
        "Comoros",
    ],
    "Southern Africa": [
        "South Africa",
        "Zimbabwe",
        "Zambia",
        "Namibia",
        "Botswana",
        "Lesotho",
        "Eswatini",
        "Malawi",
        "Mozambique",
    ],
    "Central Africa": [
        "Cameroon",
        "DR Congo",
        "Angola",
        "Gabon",
        "Republic of the Congo",
        "Central African Republic",
        "Chad",
        "Equatorial Guinea",
        "Sao Tome and Principe",
    ],
}

# Major cities for generation if needed
capitals = {
    "Egypt": "Cairo",
    "Morocco": "Rabat",
    "Algeria": "Algiers",
    "Tunisia": "Tunis",
    "Libya": "Tripoli",
    "Sudan": "Khartoum",
    "Nigeria": "Abuja",
    "Ghana": "Accra",
    "Senegal": "Dakar",
    "Cote d'Ivoire": "Yamoussoukro",
    "Benin": "Porto-Novo",
    "Burkina Faso": "Ouagadougou",
    "Cape Verde": "Praia",
    "Gambia": "Banjul",
    "Guinea": "Conakry",
    "Guinea-Bissau": "Bissau",
    "Liberia": "Monrovia",
    "Mali": "Bamako",
    "Mauritania": "Nouakchott",
    "Niger": "Niamey",
    "Sierra Leone": "Freetown",
    "Togo": "Lome",
    "Kenya": "Nairobi",
    "Uganda": "Kampala",
    "Tanzania": "Dodoma",
    "Ethiopia": "Addis Ababa",
    "Rwanda": "Kigali",
    "Burundi": "Gitega",
    "Djibouti": "Djibouti",
    "Eritrea": "Asmara",
    "Somalia": "Mogadishu",
    "South Sudan": "Juba",
    "Madagascar": "Antananarivo",
    "Mauritius": "Port Louis",
    "Seychelles": "Victoria",
    "Comoros": "Moroni",
    "South Africa": "Pretoria",
    "Zimbabwe": "Harare",
    "Zambia": "Lusaka",
    "Namibia": "Windhoek",
    "Botswana": "Gaborone",
    "Lesotho": "Maseru",
    "Eswatini": "Mbabane",
    "Malawi": "Lilongwe",
    "Mozambique": "Maputo",
    "Cameroon": "Yaounde",
    "DR Congo": "Kinshasa",
    "Angola": "Luanda",
    "Gabon": "Libreville",
    "Republic of the Congo": "Brazzaville",
    "Central African Republic": "Bangui",
    "Chad": "N'Djamena",
    "Equatorial Guinea": "Malabo",
    "Sao Tome and Principe": "Sao Tome",
}

# Hand-curated top universities to include (demo universities)
curated_universities = {
    # North Africa
    "Egypt": [
        {"name": "Cairo University", "ror": "https://ror.org/03c4mpy73"},
        {"name": "Ain Shams University", "ror": "https://ror.org/034x7p097"},
        {"name": "Alexandria University", "ror": "https://ror.org/02078r490"},
        {"name": "Mansoura University", "ror": "https://ror.org/032p18087"},
        {"name": "Assiut University", "ror": "https://ror.org/047fpp722"},
    ],
    "Morocco": [
        {"name": "Université Mohammed V de Rabat", "ror": "https://ror.org/03vpy3v17"},
        {"name": "Université Cadi Ayyad", "ror": "https://ror.org/0154pcf71"},
        {
            "name": "Université Hassan II de Casablanca",
            "ror": "https://ror.org/013y27r38",
        },
    ],
    "Tunisia": [
        {"name": "Université de Tunis El Manar", "ror": "https://ror.org/050j3a172"},
        {"name": "Université de Sfax", "ror": "https://ror.org/02157p641"},
        {"name": "Université de Carthage", "ror": "https://ror.org/011yvpy71"},
    ],
    # Central Africa
    "Cameroon": [
        {"name": "Université de Yaoundé I", "ror": "https://ror.org/04h7g6177"},
        {"name": "Université de Dschang", "ror": "https://ror.org/012y7p041"},
        {"name": "Université de Douala", "ror": "https://ror.org/041y27r28"},
    ],
    "DR Congo": [
        {"name": "Université de Kinshasa", "ror": "https://ror.org/05vzwad88"},
        {"name": "Université de Lubumbashi", "ror": "https://ror.org/02rry3m21"},
    ],
    "Angola": [
        {"name": "Université Agostinho Neto", "ror": "https://ror.org/00z2bpt98"}
    ],
    "Gabon": [
        {
            "name": "Université des Sciences et Techniques de Masuku",
            "ror": "https://ror.org/059gqse72",
        },
        {"name": "Université Omar Bongo", "ror": "https://ror.org/041yp1812"},
    ],
    "Republic of the Congo": [
        {"name": "Université Marien Ngouabi", "ror": "https://ror.org/02y1sra05"}
    ],
    # West Africa
    "Nigeria": [
        {"name": "University of Lagos", "ror": "https://ror.org/05rk03822"},
        {"name": "University of Ibadan", "ror": "https://ror.org/01es5me90"},
        {"name": "Covenant University", "ror": "https://ror.org/02n05rk12"},
        {"name": "Obafemi Awolowo University", "ror": "https://ror.org/013pcr241"},
        {"name": "University of Nigeria Nsukka", "ror": "https://ror.org/02kpy5732"},
    ],
    "Ghana": [
        {"name": "University of Ghana", "ror": "https://ror.org/00zpy3v12"},
        {
            "name": "Kwame Nkrumah University of Science and Technology",
            "ror": "https://ror.org/00x4mpy73",
        },
        {"name": "University of Cape Coast", "ror": "https://ror.org/01es3v123"},
    ],
    # Southern Africa
    "South Africa": [
        {"name": "University of Cape Town", "ror": "https://ror.org/017620319"},
        {"name": "Stellenbosch University", "ror": "https://ror.org/05777p686"},
        {"name": "University of the Witwatersrand", "ror": "https://ror.org/039482g93"},
        {"name": "University of Pretoria", "ror": "https://ror.org/047fpp722"},
        {"name": "University of KwaZulu-Natal", "ror": "https://ror.org/01267r312"},
    ],
    "Zimbabwe": [
        {"name": "University of Zimbabwe", "ror": "https://ror.org/03w489125"},
        {
            "name": "National University of Science and Technology",
            "ror": "https://ror.org/01y6mpy73",
        },
    ],
    # East Africa
    "Kenya": [
        {"name": "University of Nairobi", "ror": "https://ror.org/01078r490"},
        {"name": "Kenyatta University", "ror": "https://ror.org/01py3v171"},
        {
            "name": "Jomo Kenyatta University of Agriculture and Technology",
            "ror": "https://ror.org/03pyvpy71",
        },
    ],
    "Uganda": [
        {"name": "Makerere University", "ror": "https://ror.org/05vzwad88"},
        {
            "name": "Mbarara University of Science and Technology",
            "ror": "https://ror.org/0155pcf71",
        },
    ],
    "Tanzania": [
        {"name": "University of Dar es Salaam", "ror": "https://ror.org/0199e1957"},
        {
            "name": "Sokoine University of Agriculture",
            "ror": "https://ror.org/011y27r38",
        },
    ],
    "Ethiopia": [
        {"name": "Addis Ababa University", "ror": "https://ror.org/01py3v171"}
    ],
    "Rwanda": [{"name": "University of Rwanda", "ror": "https://ror.org/02yr01r27"}],
}

# Generate 15-20 universities for each country
registry_data = {}
for subregion, countries in subregions.items():
    registry_data[subregion] = {}
    for country in countries:
        cap = capitals.get(country, "City")
        # Start with curated list or empty
        unis = curated_universities.get(country, []).copy()

        # Add generated universities to reach 15
        existing_names = {u["name"] for u in unis}
        templates = [
            f"University of {cap}",
            f"National University of {country}",
            f"{country} University of Science and Technology",
            f"{cap} Institute of Technology",
            f"State University of {cap}",
            f"{country} International University",
            f"Pan-African University, {cap} Campus",
            f"Catholic University of {country}",
            f"Technical University of {cap}",
            (
                f"Ahmadu Bello University of {cap}"
                if country == "Nigeria"
                else f"Federal University of {cap}"
            ),
            f"Metropolitan University of {cap}",
            f"Central University of {country}",
            f"Presbyterian University of {country}",
            f"Adventist University of {country}",
            f"Islamic University of {country}",
            f"Methodist University of {country}",
            f"Covenant University of {cap}",
            f"{cap} College of Medicine and Health Sciences",
            f"Regional Institute of Information Technology, {cap}",
            f"Greenfield University, {cap}",
        ]

        idx = 0
        while len(unis) < 18:
            name = templates[idx % len(templates)]
            # ensure uniqueness
            if name not in existing_names:
                unis.append({"name": name, "ror": ""})
                existing_names.add(name)
            idx += 1

        registry_data[subregion][country] = unis

# Write university_registry.json
os.makedirs("data", exist_ok=True)
with open("data/university_registry.json", "w", encoding="utf-8") as f:
    json.dump(registry_data, f, indent=2, ensure_ascii=False)
print(
    "Generated data/university_registry.json with 52 countries and 18 universities each."
)

# Configurations for the 15 new universities to make a total of 25 demo universities
new_universities = [
    # North (5)
    {
        "file": "cairo.json",
        "ror": "https://ror.org/03c4mpy73",
        "name": "Cairo University",
        "short_name": "Cairo Univ",
        "country": "Egypt",
        "sub_region": "North Africa",
    },
    {
        "file": "ainshams.json",
        "ror": "https://ror.org/034x7p097",
        "name": "Ain Shams University",
        "short_name": "Ain Shams",
        "country": "Egypt",
        "sub_region": "North Africa",
    },
    {
        "file": "alexandria.json",
        "ror": "https://ror.org/02078r490",
        "name": "Alexandria University",
        "short_name": "Alexandria",
        "country": "Egypt",
        "sub_region": "North Africa",
    },
    {
        "file": "tunis.json",
        "ror": "https://ror.org/050j3a172",
        "name": "Université de Tunis El Manar",
        "short_name": "Tunis El Manar",
        "country": "Tunisia",
        "sub_region": "North Africa",
    },
    {
        "file": "mohammedv.json",
        "ror": "https://ror.org/03vpy3v17",
        "name": "Université Mohammed V de Rabat",
        "short_name": "Mohammed V",
        "country": "Morocco",
        "sub_region": "North Africa",
    },
    # Central (5)
    {
        "file": "yaoundei.json",
        "ror": "https://ror.org/04h7g6177",
        "name": "Université de Yaoundé I",
        "short_name": "Yaoundé I",
        "country": "Cameroon",
        "sub_region": "Central Africa",
    },
    {
        "file": "kinshasa.json",
        "ror": "https://ror.org/05vzwad88",
        "name": "Université de Kinshasa",
        "short_name": "UNIKIN",
        "country": "DR Congo",
        "sub_region": "Central Africa",
    },
    {
        "file": "agostinhoneto.json",
        "ror": "https://ror.org/00z2bpt98",
        "name": "Université Agostinho Neto",
        "short_name": "Agostinho Neto",
        "country": "Angola",
        "sub_region": "Central Africa",
    },
    {
        "file": "marienngouabi.json",
        "ror": "https://ror.org/02y1sra05",
        "name": "Université Marien Ngouabi",
        "short_name": "Marien Ngouabi",
        "country": "Republic of the Congo",
        "sub_region": "Central Africa",
    },
    {
        "file": "masuku.json",
        "ror": "https://ror.org/059gqse72",
        "name": "Université des Sciences et Techniques de Masuku",
        "short_name": "USTM Masuku",
        "country": "Gabon",
        "sub_region": "Central Africa",
    },
    # Southern (+3 new ones)
    {
        "file": "wits.json",
        "ror": "https://ror.org/039482g93",
        "name": "University of the Witwatersrand",
        "short_name": "Wits",
        "country": "South Africa",
        "sub_region": "Southern Africa",
    },
    {
        "file": "pretoria.json",
        "ror": "https://ror.org/047fpp722",
        "name": "University of Pretoria",
        "short_name": "UP",
        "country": "South Africa",
        "sub_region": "Southern Africa",
    },
    {
        "file": "zimbabwe.json",
        "ror": "https://ror.org/03w489125",
        "name": "University of Zimbabwe",
        "short_name": "UZ",
        "country": "Zimbabwe",
        "sub_region": "Southern Africa",
    },
    # East (+2 new ones)
    {
        "file": "daressalaam.json",
        "ror": "https://ror.org/0199e1957",
        "name": "University of Dar es Salaam",
        "short_name": "UDSM",
        "country": "Tanzania",
        "sub_region": "East Africa",
    },
    {
        "file": "rwanda.json",
        "ror": "https://ror.org/02yr01r27",
        "name": "University of Rwanda",
        "short_name": "UR",
        "country": "Rwanda",
        "sub_region": "East Africa",
    },
]

# Write institutional configs
os.makedirs("config/institutions", exist_ok=True)
for u in new_universities:
    cfg = {
        "ror": u["ror"],
        "name": u["name"],
        "short_name": u["short_name"],
        "country": u["country"],
        "sub_region": u["sub_region"],  # explicitly add sub-region to config files
        "staff_file": f"data/{u['short_name'].lower().replace(' ', '_')}_staff.json",
        "affiliation_patterns": [u["name"], u["short_name"], f"{u['name']} Department"],
        "faculties": [
            "Science",
            "Humanities",
            "Engineering",
            "Medicine",
            "Social Sciences",
            "Arts",
            "Law",
        ],
        "crawler_settings": {
            "rate_limit": 2.0,
            "concurrent_requests": 8,
            "retry_times": 3,
            "download_delay": 2.0,
        },
    }
    with open(f"config/institutions/{u['file']}", "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

print("Generated 15 new institutional config files.")
