"""
Manual ROR lookup for institutions not found by name search.
Uses OpenAlex institution search with alternate spellings/names.
"""
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path

BASE = "https://api.openalex.org"
MAILTO = "cokiki@unilag.edu.ng"

# Alternate search terms for institutions not found by direct name
ALTERNATES = {
    "agostinhoneto.json": ["Agostinho Neto", "UAN Angola", "Luanda university"],
    "kinshasa.json": ["Kinshasa university", "UNIKIN", "Congo kinshasa"],
    "marienngouabi.json": ["Marien Ngouabi", "Brazzaville university", "Congo Brazzaville"],
    "masuku.json": ["Masuku", "Franceville", "Gabon university science"],
    "mohammedv.json": ["Mohammed V", "Rabat university", "Mohammed 5"],
    "tunis.json": ["Tunis El Manar", "Tunis university", "UTM Tunisia"],
    "yaoundei.json": ["Yaounde", "Cameroon university", "Yaounde 1"],
}

config_dir = Path(__file__).parent.parent / "config" / "institutions"

for fname, search_terms in ALTERNATES.items():
    jf = config_dir / fname
    with open(jf) as f:
        data = json.load(f)
    name = data["name"]
    print(f"\n=== {name} ===")
    
    found = False
    for term in search_terms:
        q = urllib.parse.quote(term)
        url = f"{BASE}/institutions?search={q}&per-page=5&mailto={MAILTO}"
        try:
            req = urllib.request.urlopen(url, timeout=15)
            resp = json.loads(req.read())
            results = resp.get("results", [])
        except Exception as e:
            print(f"  ERROR searching {term!r}: {e}")
            time.sleep(1)
            continue
        
        if results:
            print(f"  Search '{term}' -> {len(results)} results:")
            for r in results[:3]:
                print(f"    [{r['works_count']:6d} works] {r['display_name']} | ROR: {r['ror']}")
            found = True
        else:
            print(f"  Search '{term}' -> no results")
        time.sleep(0.4)
        if found:
            break
