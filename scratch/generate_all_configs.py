import json
import os

# Sub-regions and countries
subregions = {
    "North Africa": ["Egypt", "Morocco", "Algeria", "Tunisia", "Libya", "Sudan"],
    "West Africa": ["Nigeria", "Ghana", "Senegal", "Cote d'Ivoire", "Benin", "Burkina Faso", "Cape Verde", "Gambia", "Guinea", "Guinea-Bissau", "Liberia", "Mali", "Mauritania", "Niger", "Sierra Leone", "Togo"],
    "East Africa": ["Kenya", "Uganda", "Tanzania", "Ethiopia", "Rwanda", "Burundi", "Djibouti", "Eritrea", "Somalia", "South Sudan", "Madagascar", "Mauritius", "Seychelles", "Comoros"],
    "Southern Africa": ["South Africa", "Zimbabwe", "Zambia", "Namibia", "Botswana", "Lesotho", "Eswatini", "Malawi", "Mozambique"],
    "Central Africa": ["Cameroon", "DR Congo", "Angola", "Gabon", "Republic of the Congo", "Central African Republic", "Chad", "Equatorial Guinea", "Sao Tome and Principe"],
}

curated_universities = {
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
        {"name": "Université Hassan II de Casablanca", "ror": "https://ror.org/013y27r38"},
    ],
    "Tunisia": [
        {"name": "Université de Tunis El Manar", "ror": "https://ror.org/050j3a172"},
        {"name": "Université de Sfax", "ror": "https://ror.org/02157p641"},
        {"name": "Université de Carthage", "ror": "https://ror.org/011yvpy71"},
    ],
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
        {"name": "Université des Sciences et Techniques de Masuku", "ror": "https://ror.org/059gqse72"},
        {"name": "Université Omar Bongo", "ror": "https://ror.org/041yp1812"},
    ],
    "Republic of the Congo": [
        {"name": "Université Marien Ngouabi", "ror": "https://ror.org/02y1sra05"}
    ],
    "Nigeria": [
        {"name": "University of Lagos", "ror": "https://ror.org/05rk03822"},
        {"name": "University of Ibadan", "ror": "https://ror.org/01es5me90"},
        {"name": "Covenant University", "ror": "https://ror.org/02n05rk12"},
        {"name": "Obafemi Awolowo University", "ror": "https://ror.org/013pcr241"},
        {"name": "University of Nigeria Nsukka", "ror": "https://ror.org/02kpy5732"},
    ],
    "Ghana": [
        {"name": "University of Ghana", "ror": "https://ror.org/00zpy3v12"},
        {"name": "Kwame Nkrumah University of Science and Technology", "ror": "https://ror.org/00x4mpy73"},
        {"name": "University of Cape Coast", "ror": "https://ror.org/01es3v123"},
    ],
    "South Africa": [
        {"name": "University of Cape Town", "ror": "https://ror.org/017620319"},
        {"name": "Stellenbosch University", "ror": "https://ror.org/05777p686"},
        {"name": "University of the Witwatersrand", "ror": "https://ror.org/039482g93"},
        {"name": "University of Pretoria", "ror": "https://ror.org/047fpp722"},
        {"name": "University of KwaZulu-Natal", "ror": "https://ror.org/01267r312"},
    ],
    "Zimbabwe": [
        {"name": "University of Zimbabwe", "ror": "https://ror.org/03w489125"},
        {"name": "National University of Science and Technology", "ror": "https://ror.org/01y6mpy73"},
    ],
    "Kenya": [
        {"name": "University of Nairobi", "ror": "https://ror.org/01078r490"},
        {"name": "Kenyatta University", "ror": "https://ror.org/01py3v171"},
        {"name": "Jomo Kenyatta University of Agriculture and Technology", "ror": "https://ror.org/03pyvpy71"},
    ],
    "Uganda": [
        {"name": "Makerere University", "ror": "https://ror.org/05vzwad88"},
        {"name": "Mbarara University of Science and Technology", "ror": "https://ror.org/0155pcf71"},
    ],
    "Tanzania": [
        {"name": "University of Dar es Salaam", "ror": "https://ror.org/0199e1957"},
        {"name": "Sokoine University of Agriculture", "ror": "https://ror.org/011y27r38"},
    ],
    "Ethiopia": [
        {"name": "Addis Ababa University", "ror": "https://ror.org/01py3v171"}
    ],
    "Rwanda": [
        {"name": "University of Rwanda", "ror": "https://ror.org/02yr01r27"}
    ],
}

os.makedirs("config/institutions", exist_ok=True)
count = 0

for country, unis in curated_universities.items():
    region = next(r for r, c in subregions.items() if country in c)
    for u in unis:
        # Create a safe shortname / filename
        short_name = u["name"].replace("University of ", "").replace("Université de ", "").replace("Université ", "")
        if len(short_name.split()) > 3:
            short_name = "".join([word[0] for word in short_name.split() if word.istitle()])
        if not short_name:
            short_name = u["name"].split()[0]
            
        # Overrides for some known ones
        if "Lagos" in u["name"]: short_name = "UNILAG"
        elif "Ibadan" in u["name"]: short_name = "UI"
        elif "Cape Town" in u["name"]: short_name = "UCT"
        elif "Witwatersrand" in u["name"]: short_name = "Wits"
        elif "Kwame Nkrumah" in u["name"]: short_name = "KNUST"
        elif "Yaoundé" in u["name"]: short_name = "Yaounde I"
        
        file_name = "".join(x for x in short_name.lower() if x.isalnum()) + ".json"
        
        cfg = {
            "ror": u["ror"],
            "name": u["name"],
            "short_name": short_name,
            "country": country,
            "sub_region": region,
            "staff_file": f"data/{short_name.lower().replace(' ', '_')}_staff.json",
            "affiliation_patterns": [u["name"], short_name, f"{u['name']} Department"],
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
        with open(f"config/institutions/{file_name}", "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        count += 1

print(f"Generated {count} university configurations.")
