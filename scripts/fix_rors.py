import glob
import json
import os
import urllib.parse
import urllib.request

files = glob.glob("config/institutions/*.json")

for fpath in files:
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    name = data.get("name")
    if not name:
        continue

    url = f"https://api.openalex.org/institutions?search={urllib.parse.quote(name)}&per-page=1"
    try:
        res = json.loads(urllib.request.urlopen(url).read().decode())["results"][0]
        correct_ror = res.get("ror")
        if correct_ror and correct_ror != data.get("ror"):
            print(f"Updating {name}: {data.get('ror')} -> {correct_ror}")
            data["ror"] = correct_ror
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error for {name}: {e}")
