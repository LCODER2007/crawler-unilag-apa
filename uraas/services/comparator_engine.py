"""
Multi-Institution Comparator Engine
Core feature of APA Intelligence Platform - allows comparing multiple African universities
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import distinct, func
from sqlalchemy.orm import aliased

from uraas.database import (
    Author,
    Collection,
    Community,
    File,
    Item,
    SessionLocal,
    item_authors,
)


class InstitutionProfile:
    """Profile data for a single institution"""

    def __init__(self, ror_id: str, name: str):
        self.ror_id = ror_id
        self.name = name
        self.metrics = {}

    def calculate_metrics(self, session):
        """Calculate all metrics for this institution"""

        # Basic counts
        items = session.query(Item).filter(Item.ror == self.ror_id).all()
        self.metrics["total_papers"] = len(items)
        self.metrics["total_authors"] = (
            session.query(func.count(distinct(Author.id)))
            .select_from(Author)
            .join(Author.items)
            .filter(Item.ror == self.ror_id)
            .scalar()
        ) or 0

        # Open Access
        oa_count = sum(1 for i in items if "openAccess" in (i.dc_rights or ""))
        self.metrics["open_access_count"] = oa_count
        self.metrics["oa_rate"] = round(oa_count / len(items) * 100, 1) if items else 0

        # Indigenous Knowledge
        tk_count = sum(
            1 for i in items if i.tk_label or i.content_type == "indigenous_knowledge"
        )
        self.metrics["tk_papers"] = tk_count
        self.metrics["tk_rate"] = round(tk_count / len(items) * 100, 1) if items else 0

        # Patents
        patent_count = sum(1 for i in items if i.patent_id)
        self.metrics["patents"] = patent_count
        self.metrics["patent_rate"] = (
            round(patent_count / len(items) * 100, 1) if items else 0
        )

        # African Languages
        african_lang_count = sum(1 for i in items if i.is_african_language)
        self.metrics["african_language_papers"] = african_lang_count
        self.metrics["african_lang_rate"] = (
            round(african_lang_count / len(items) * 100, 1) if items else 0
        )

        # Temporal analysis
        years = [i.publication_date.year for i in items if i.publication_date]
        if years:
            self.metrics["year_range"] = [min(years), max(years)]
            self.metrics["years_active"] = max(years) - min(years) + 1

            # Growth rate (last 3 years vs previous 3 years)
            current_year = datetime.now().year
            recent = sum(1 for y in years if y >= current_year - 3)
            previous = sum(1 for y in years if current_year - 6 <= y < current_year - 3)
            self.metrics["growth_rate"] = (
                round((recent - previous) / previous * 100, 1) if previous else 0
            )
        else:
            self.metrics["year_range"] = []
            self.metrics["years_active"] = 0
            self.metrics["growth_rate"] = 0

        # Efficiency ratios
        self.metrics["papers_per_author"] = (
            round(len(items) / self.metrics["total_authors"], 2)
            if self.metrics["total_authors"]
            else 0
        )
        self.metrics["patents_per_100_papers"] = (
            round(patent_count / len(items) * 100, 1) if items else 0
        )

        # DocID coverage
        docid_count = sum(1 for i in items if i.docid)
        self.metrics["docid_coverage"] = (
            round(docid_count / len(items) * 100, 1) if items else 0
        )

        # Sub-region lookup from registry
        from uraas.config.institutions import get_registry

        reg = get_registry()
        inst_cfg = reg.get(self.ror_id)
        self.metrics["sub_region"] = inst_cfg.sub_region if inst_cfg else "Unknown"

        return self.metrics


class ComparatorEngine:
    """
    Multi-Institution Comparison Engine
    Allows comparing 2-15 institutions simultaneously across all African universities
    """

    @staticmethod
    def compare_institutions(ror_ids: List[str]) -> Dict:
        """
        Compare multiple institutions across all metrics

        Args:
            ror_ids: List of ROR identifiers for institutions

        Returns:
            Comprehensive comparison data structure
        """
        session = SessionLocal()
        try:
            profiles = []

            for ror_id in ror_ids:
                # Get institution name from first paper or use ROR
                item = session.query(Item).filter(Item.ror == ror_id).first()
                name = item.institution if item else ror_id

                profile = InstitutionProfile(ror_id, name)
                profile.calculate_metrics(session)
                profiles.append(profile)

            # Build comparison matrix
            comparison = {
                "institutions": [
                    {"ror_id": p.ror_id, "name": p.name, "metrics": p.metrics}
                    for p in profiles
                ],
                "rankings": ComparatorEngine._calculate_rankings(profiles),
                "insights": ComparatorEngine._generate_insights(profiles),
            }

            return comparison

        finally:
            session.close()

    @staticmethod
    def _calculate_rankings(profiles: List[InstitutionProfile]) -> Dict:
        """Calculate rankings across key metrics"""

        rankings = {}

        metrics_to_rank = [
            "total_papers",
            "oa_rate",
            "tk_rate",
            "patent_rate",
            "african_lang_rate",
            "growth_rate",
            "papers_per_author",
            "patents_per_100_papers",
        ]

        for metric in metrics_to_rank:
            sorted_profiles = sorted(
                profiles, key=lambda p: p.metrics.get(metric, 0), reverse=True
            )
            rankings[metric] = [
                {
                    "rank": i + 1,
                    "institution": p.name,
                    "value": p.metrics.get(metric, 0),
                }
                for i, p in enumerate(sorted_profiles)
            ]

        return rankings

    @staticmethod
    def _generate_insights(profiles: List[InstitutionProfile]) -> List[Dict]:
        """Generate strategic insights from comparison"""

        insights = []

        # Find leader in each category
        categories = {
            "total_papers": "Research Volume Leader",
            "oa_rate": "Open Access Champion",
            "tk_rate": "Indigenous Knowledge Preservation Leader",
            "patent_rate": "Innovation Commercialization Leader",
            "african_lang_rate": "Linguistic Diversity Champion",
            "growth_rate": "Fastest Growing Institution",
        }

        for metric, title in categories.items():
            leader = max(profiles, key=lambda p: p.metrics.get(metric, 0))
            if leader.metrics.get(metric, 0) > 0:
                insights.append(
                    {
                        "category": title,
                        "institution": leader.name,
                        "value": leader.metrics.get(metric, 0),
                        "metric": metric,
                    }
                )

        # Identify gaps
        for profile in profiles:
            if profile.metrics.get("tk_rate", 0) < 5:
                insights.append(
                    {
                        "category": "Opportunity",
                        "institution": profile.name,
                        "message": "Low indigenous knowledge digitization - opportunity for cultural preservation initiatives",
                        "metric": "tk_rate",
                    }
                )

            if profile.metrics.get("patent_rate", 0) < 2:
                insights.append(
                    {
                        "category": "Opportunity",
                        "institution": profile.name,
                        "message": "Low patent-to-paper ratio - opportunity to strengthen innovation commercialization",
                        "metric": "patent_rate",
                    }
                )

        return insights

    @staticmethod
    def get_collaboration_matrix(ror_ids: List[str]) -> Dict:
        """
        Calculate collaboration patterns between institutions
        Returns data for Collaboration Mesh visualization
        """
        session = SessionLocal()
        try:
            # Find papers with authors from multiple institutions
            collaborations = {}

            for ror1 in ror_ids:
                for ror2 in ror_ids:
                    if ror1 >= ror2:  # Avoid duplicates
                        continue

                    # Count co-authored papers: distinct papers at ror1 that share at least one
                    # author with a paper at ror2. Self-join Item via the item_authors table.
                    i1 = aliased(Item, name="i1")
                    i2 = aliased(Item, name="i2")
                    ia1 = item_authors.alias("ia1")
                    ia2 = item_authors.alias("ia2")
                    count = (
                        session.query(func.count(distinct(i1.id)))
                        .select_from(i1)
                        .join(ia1, ia1.c.item_id == i1.id)
                        .join(ia2, ia2.c.author_id == ia1.c.author_id)
                        .join(i2, i2.id == ia2.c.item_id)
                        .filter(i1.ror == ror1, i2.ror == ror2)
                        .scalar()
                    ) or 0

                    if count > 0:
                        key = f"{ror1}_{ror2}"
                        collaborations[key] = {
                            "source": ror1,
                            "target": ror2,
                            "weight": count,
                        }

            return {
                "nodes": [{"id": ror, "label": ror} for ror in ror_ids],
                "edges": list(collaborations.values()),
            }

        finally:
            session.close()

    @staticmethod
    def generate_senate_report(ror_ids: List[str], format: str = "json") -> Dict:
        """
        Generate comprehensive report for university senate

        Args:
            ror_ids: Institutions to include
            format: 'json', 'csv', or 'pdf'

        Returns:
            Structured report data
        """
        comparison = ComparatorEngine.compare_institutions(ror_ids)
        collaboration = ComparatorEngine.get_collaboration_matrix(ror_ids)

        report = {
            "title": "APA Intelligence Platform - Institutional Comparison Report",
            "generated_at": datetime.utcnow().isoformat(),
            "institutions_analyzed": len(ror_ids),
            "executive_summary": {
                "total_papers": sum(
                    i["metrics"]["total_papers"] for i in comparison["institutions"]
                ),
                "total_authors": sum(
                    i["metrics"]["total_authors"] for i in comparison["institutions"]
                ),
                "average_oa_rate": round(
                    sum(i["metrics"]["oa_rate"] for i in comparison["institutions"])
                    / len(ror_ids),
                    1,
                ),
                "total_collaborations": len(collaboration["edges"]),
            },
            "detailed_comparison": comparison,
            "collaboration_network": collaboration,
            "recommendations": ComparatorEngine._generate_recommendations(comparison),
        }

        return report

    @staticmethod
    def _generate_recommendations(comparison: Dict) -> List[str]:
        """Generate strategic recommendations based on comparison"""

        recommendations = []

        # Analyze patterns
        institutions = comparison["institutions"]
        avg_oa = sum(i["metrics"]["oa_rate"] for i in institutions) / len(institutions)
        avg_tk = sum(i["metrics"]["tk_rate"] for i in institutions) / len(institutions)

        if avg_oa < 50:
            recommendations.append(
                "Regional open access rates below 50 percent - recommend coordinated OA policy development"
            )

        if avg_tk < 10:
            recommendations.append(
                "Low indigenous knowledge digitization across region - opportunity for APA-led cultural preservation initiative"
            )

        # Find best practices
        tk_leader = max(institutions, key=lambda i: i["metrics"]["tk_rate"])
        if tk_leader["metrics"]["tk_rate"] > 20:
            recommendations.append(
                f"{tk_leader['name']} demonstrates strong indigenous knowledge preservation ({tk_leader['metrics']['tk_rate']}%) - recommend knowledge sharing workshop"
            )

        return recommendations
