import re

with open("uraas/dashboard/templates/index.html", "r", encoding="utf-8") as f:
    content = f.read()

# Find the special collections section and replace it
pattern = r"(    \s*<!--\s+SPECIAL COLLECTIONS.*?</div>\n\n  </div><!-- end analytics tab -->)"
replacement = """    
    <!--  SPECIAL COLLECTIONS  -->
    <div id="atab-special" class="atab-content hidden">
      <div class="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 class="text-xl font-bold mb-1" style="color:var(--text)">Special Collections: African Literature &amp; Indigenous Knowledge</h2>
          <p class="text-sm" style="color:var(--text-muted)">AI-powered classification: Postcolonial Studies, Pan-African Studies, Ethnomusicology &amp; more.</p>
        </div>
        <a href="/api/analytics/special-collections/export.csv" class="btn-ghost text-xs flex-shrink-0">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
          Download CSV
        </a>
      </div>
      <div id="special-loading" class="flex items-center gap-3 py-10 justify-center">
        <div class="w-6 h-6 border-2 rounded-full animate-spin" style="border-color:var(--accent);border-top-color:transparent"></div>
        <p class="text-sm" style="color:var(--text-muted)">Analyzing special collections...</p>
      </div>
      <div id="special-content" class="hidden">
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-5 mb-6" id="special-stats"></div>
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-5" id="special-categories"></div>
      </div>
    </div>

    <!--  STAFF DIRECTORY  -->
    <div id="atab-staff" class="atab-content hidden">
      <div class="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 class="text-xl font-bold mb-1" style="color:var(--text)">Staff Directory</h2>
          <p class="text-sm" style="color:var(--text-muted)">Real staff members with departments and ORCID identifiers, harvested from OpenAlex and ORCID APIs.</p>
        </div>
        <select id="staff-inst-filter" onchange="loadStaffDirectory()" style="width:auto;font-size:12px;padding:5px 10px">
          <option value="">All Institutions</option>
          <option value="unilag">UNILAG</option><option value="covenant">Covenant</option>
          <option value="ui">Univ. Ibadan</option><option value="uct">UCT</option>
          <option value="stellenbosch">Stellenbosch</option><option value="nairobi">Nairobi</option>
          <option value="makerere">Makerere</option><option value="ghana">Univ. Ghana</option>
          <option value="addisababa">Addis Ababa</option><option value="knust">KNUST</option>
        </select>
      </div>
      <div id="staff-loading" class="flex items-center gap-3 py-10 justify-center">
        <div class="w-6 h-6 border-2 rounded-full animate-spin" style="border-color:var(--accent);border-top-color:transparent"></div>
        <p class="text-sm" style="color:var(--text-muted)">Loading staff directory...</p>
      </div>
      <div id="staff-content" class="hidden">
        <div id="staff-institutions-list" class="space-y-6"></div>
      </div>
    </div>

  </div><!-- end analytics tab -->"""

new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
if new_content == content:
    print("ERROR: Pattern not matched. Trying direct string replace...")
    # Try to find where special collections starts
    idx = content.find("<!--  SPECIAL COLLECTIONS  -->")
    print(f"Found at index: {idx}")
    if idx >= 0:
        end_marker = "  </div><!-- end analytics tab -->"
        end_idx = content.find(end_marker, idx)
        print(f"End marker at: {end_idx}")
        segment = content[idx : end_idx + len(end_marker)]
        print(f"Segment length: {len(segment)}")
        print("First 200 chars:", repr(segment[:200]))
else:
    with open("uraas/dashboard/templates/index.html", "w", encoding="utf-8") as f:
        f.write(new_content)
    print("SUCCESS")
