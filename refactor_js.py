import re

path = "uraas/dashboard/static/js/app.js"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

# Remove SDG references from variables
text = re.sub(r"sdgData = null, ", "", text)
text = re.sub(r"sdgLoaded = false, ", "", text)
text = re.sub(r"if \(name === 'sdg'\) loadSDGTab\(\);\n\s*", "", text)
text = re.sub(
    r"const sdgCsv = \$\('sdg-csv-btn'\); if \(sdgCsv\) sdgCsv\.href = '/api/analytics/sdg-alignment/export\.csv' \+ qs;\n\s*",
    "",
    text,
)
text = re.sub(
    r"else if \(currentAtab === 'sdg'\) \{ sdgLoaded = false; loadSDGTab\(\); \}",
    "",
    text,
)

# Remove the entire block of SDG functions
# Starts at `/* SDG Alignment */` or `const SDG_COLORS` and ends at `function closeSdgPanel`
text = re.sub(
    r"/\*\s*SDG Alignment\s*\*/.*?function closeSdgPanel\(\) \{ \$\(\'sdg-papers-panel\'\)\?\.classList\.add\(\'hidden\'\); \}",
    "",
    text,
    flags=re.DOTALL,
)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)

print("SDG JS removed.")
