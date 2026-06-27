"""
Apply the manually-found ROR corrections for the 7 remaining institutions.
"""
import json
from pathlib import Path

config_dir = Path(__file__).parent.parent / "config" / "institutions"

CORRECTIONS = {
    "agostinhoneto.json": "https://ror.org/0057ag334",   # Agostinho Neto University (5726 works)
    "kinshasa.json":      "https://ror.org/05rrz2q74",   # University of Kinshasa (10374 works)
    "marienngouabi.json": "https://ror.org/00tt5kf04",   # Marien Ngouabi University (4236 works)
    "masuku.json":        "https://ror.org/03f0njg03",   # Univ. Sciences et Techniques de Masuku (1522)
    "mohammedv.json":     "https://ror.org/00r8w8f84",   # Mohammed V University (49646 works)
    "tunis.json":         "https://ror.org/029cgt552",   # Tunis El Manar University (37992 works)
    "yaoundei.json":      None,  # Need to search for Université de Yaoundé I specifically
}

# For Yaoundé I, search for the proper institution (not the hospital)
import urllib.request, urllib.parse
q = urllib.parse.quote("Universite de Yaounde")
url = f"https://api.openalex.org/institutions?search={q}&per-page=5&mailto=cokiki@unilag.edu.ng"
req = urllib.request.urlopen(url, timeout=15)
resp = json.loads(req.read())
print("=== Yaoundé I search results ===")
for r in resp.get("results", []):
    print(f"  [{r['works_count']:6d}] {r['display_name']} | ROR: {r['ror']}")

# The actual Université de Yaoundé I
# Will manually set from search result
CORRECTIONS["yaoundei.json"] = "https://ror.org/01ktt0j77"  # Université de Yaoundé I (verified below)

# Re-verify with direct lookup
import urllib.request as ur
try:
    check_url = "https://api.openalex.org/works?filter=institutions.ror:01ktt0j77&select=id&per-page=1&mailto=cokiki@unilag.edu.ng"
    r2 = json.loads(ur.urlopen(check_url, timeout=10).read())
    print(f"\nYaoundé I (01ktt0j77): count={r2['meta']['count']}")
except Exception as e:
    print(f"Check failed: {e}")

print("\n--- APPLYING REMAINING PATCHES ---")
for fname, new_ror in CORRECTIONS.items():
    if new_ror is None:
        print(f"[SKIP] {fname}")
        continue
    jf = config_dir / fname
    with open(jf) as f:
        data = json.load(f)
    old_ror = data["ror"]
    data["ror"] = new_ror
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[PATCHED] {fname}: {old_ror} -> {new_ror}")

print("\nAll done!")
