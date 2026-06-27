"""
Lookup correct RORs from OpenAlex for all broken institutions,
then patch the JSON files automatically.
"""
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path

BASE = "https://api.openalex.org"
MAILTO = "cokiki@unilag.edu.ng"

# Institutions we know are broken (from verify_rors.py output)
BROKEN = [
    "agostinhoneto.json",
    "ainshams.json",
    "alexandria.json",
    "cairo.json",
    "daressalaam.json",
    "kinshasa.json",
    "marienngouabi.json",
    "masuku.json",
    "mohammedv.json",
    "pretoria.json",
    "rwanda.json",
    "tunis.json",
    "wits.json",
    "yaoundei.json",
    "zimbabwe.json",
]

config_dir = Path(__file__).parent.parent / "config" / "institutions"
fixes = {}

for fname in BROKEN:
    jf = config_dir / fname
    with open(jf) as f:
        data = json.load(f)

    name = data["name"]
    q = urllib.parse.quote(name)
    url = f"{BASE}/institutions?search={q}&per-page=3&mailto={MAILTO}"

    try:
        req = urllib.request.urlopen(url, timeout=15)
        resp = json.loads(req.read())
        results = resp.get("results", [])
    except Exception as e:
        print(f"[ERROR] {name}: {e}")
        fixes[fname] = None
        time.sleep(1)
        continue

    if not results:
        print(f"[NOT FOUND] {name}")
        fixes[fname] = None
    else:
        best = results[0]
        ror = best["ror"]  # e.g. "https://ror.org/00cb9w016"
        ror_short = ror.split("/")[-1]
        count = best.get("works_count", "?")
        display = best["display_name"]
        print(f"[FOUND] {name!r}")
        print(f"        OpenAlex: {display!r}")
        print(f"        ROR: {ror}  (works: {count})")
        if count == 0:
            print(f"        WARNING: works_count=0 — double check!")
        fixes[fname] = ror

    time.sleep(0.4)

# Now apply the patches
print("\n--- APPLYING PATCHES ---")
for fname, new_ror in fixes.items():
    if new_ror is None:
        print(f"[SKIP] {fname} — no ROR found")
        continue
    jf = config_dir / fname
    with open(jf) as f:
        data = json.load(f)
    old_ror = data["ror"]
    if old_ror == new_ror:
        print(f"[SAME] {fname} — already correct")
        continue
    data["ror"] = new_ror
    with open(jf, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[PATCHED] {fname}: {old_ror} -> {new_ror}")

print("\nDone. Run verify_rors.py again to confirm all are fixed.")
