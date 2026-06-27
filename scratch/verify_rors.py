"""
Script to verify all institution RORs against OpenAlex API.
Identifies wrong RORs by checking if count > 0.
"""
import json
import time
import urllib.request
from pathlib import Path

BASE = "https://api.openalex.org"
MAILTO = "cokiki@unilag.edu.ng"

config_dir = Path(__file__).parent.parent / "config" / "institutions"
results = {}

for jf in sorted(config_dir.glob("*.json")):
    with open(jf) as f:
        data = json.load(f)
    name = data["name"]
    ror_full = data["ror"]
    ror_short = ror_full.split("/")[-1]

    url = f"{BASE}/works?filter=institutions.ror:{ror_short}&select=id&per-page=1&mailto={MAILTO}"
    try:
        req = urllib.request.urlopen(url, timeout=10)
        resp = json.loads(req.read())
        count = resp["meta"]["count"]
    except Exception as e:
        count = f"ERROR: {e}"

    status = "OK" if isinstance(count, int) and count > 0 else "ZERO/ERROR"
    print(f"[{status:5}] {name:40s}  ROR: {ror_short}  count={count}")
    results[jf.name] = {"name": name, "ror": ror_short, "count": count, "status": status}
    time.sleep(0.5)

print("\n--- PROBLEM INSTITUTIONS ---")
for fname, r in results.items():
    if r["status"] != "OK":
        print(f"  {fname}: {r['name']} -- ROR {r['ror']} returns {r['count']}")
