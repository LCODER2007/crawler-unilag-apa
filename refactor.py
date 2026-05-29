import re
import os

path = "uraas/analytics/engine.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

# 1. Update get_top_authors
text = text.replace(
    "def get_top_authors(self, limit: int = 15, community_id: Optional[int] = None) -> List[Dict]:",
    "def get_top_authors(self, limit: int = 15, community_id: Optional[int] = None, institution: Optional[str] = None) -> List[Dict]:",
)
text = text.replace(
    "if community_id:\n                q = q.join(Item.collections).join(Collection.community).filter(Community.id == community_id)",
    "if community_id:\n                q = q.join(Item.collections).join(Collection.community).filter(Community.id == community_id)\n            sc_ids = self._get_sc_item_ids(session, institution)\n            if sc_ids:\n                q = q.filter(Item.id.in_(sc_ids))\n            else:\n                return []",
)

# 2. Update get_department_collaboration_network
text = text.replace(
    "def get_department_collaboration_network(self) -> List[Dict]:",
    "def get_department_collaboration_network(self, institution: Optional[str] = None) -> List[Dict]:",
)
text = text.replace(
    "docs = session.query(Item).options(joinedload(Item.collections)).all()",
    "sc_ids = self._get_sc_item_ids(session, institution)\n            if not sc_ids:\n                return []\n            docs = session.query(Item).filter(Item.id.in_(sc_ids)).options(joinedload(Item.collections)).all()",
)

# 3. Update get_papers_by_faculty_and_department (special case, inside a loop)
p1 = """                    if inst_name:
                        q = q.filter(Item.institution.ilike(f'%{inst_name}%'))"""
p2 = """                    if inst_name:
                        q = q.filter(Item.institution.ilike(f'%{inst_name}%'))
                    sc_ids = self._get_sc_item_ids(session, institution)
                    if sc_ids:
                        q = q.filter(Item.id.in_(sc_ids))
                    else:
                        continue"""
text = text.replace(p1, p2)

p3 = """            if inst_name:
                unclassified_q = unclassified_q.filter(Item.institution.ilike(f'%{inst_name}%'))"""
p4 = """            if inst_name:
                unclassified_q = unclassified_q.filter(Item.institution.ilike(f'%{inst_name}%'))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                unclassified_q = unclassified_q.filter(Item.id.in_(sc_ids))"""
text = text.replace(p3, p4)

# 4. Update the standard query filters for all other methods
std1 = """            if inst_name:
                q = q.filter(Item.institution.ilike(f'%{inst_name}%'))"""
std2 = """            if inst_name:
                q = q.filter(Item.institution.ilike(f'%{inst_name}%'))
            sc_ids = self._get_sc_item_ids(session, institution)
            if sc_ids:
                q = q.filter(Item.id.in_(sc_ids))
            else:
                return []"""

# Since we already replaced p3, std1 will match the rest.
text = text.replace(std1, std2)

# Oh wait, for get_author_network, there's no inst_name filter, but it queries by author name.
text = text.replace(
    "items = session.query(Item).join(Item.authors).filter(Author.name == author_name).all()",
    'sc_ids = self._get_sc_item_ids(session, None)\n            if not sc_ids:\n                return {"nodes": [], "links": []}\n            items = session.query(Item).filter(Item.id.in_(sc_ids)).join(Item.authors).filter(Author.name == author_name).all()',
)

# Fix get_docid_coverage
text = text.replace(
    "q = session.query(Item.id, Item.docid, Item.doi, Item.url)",
    'sc_ids = self._get_sc_item_ids(session)\n            if not sc_ids:\n                return {"total": 0, "with_docid": 0, "without_docid": 0, "with_doi": 0}\n            q = session.query(Item.id, Item.docid, Item.doi, Item.url).filter(Item.id.in_(sc_ids))',
)

# Fix get_institution_leaderboard
text = text.replace(
    "q = session.query(Item.institution, func.count(Item.id).label('count'))",
    "sc_ids = self._get_sc_item_ids(session)\n            q = session.query(Item.institution, func.count(Item.id).label('count'))\n            if sc_ids:\n                q = q.filter(Item.id.in_(sc_ids))",
)


with open("uraas/analytics/engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Replacement complete.")
