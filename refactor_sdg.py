import re

path = "uraas/analytics/engine.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

# Remove get_sdg_alignment
text = re.sub(
    r'def get_sdg_alignment\(.*?return results\n\s*finally:\n\s*session\.close\(\)\n',
    '',
    text,
    flags=re.DOTALL
)

# Remove get_sdg_csv_data
text = re.sub(
    r'def get_sdg_csv_data\(.*?return output\n',
    '',
    text,
    flags=re.DOTALL
)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)

print("SDG methods removed.")
