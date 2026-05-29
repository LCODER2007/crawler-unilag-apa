"""
URAAS Institution Configuration System
Manages multi-institution support with ROR identifiers
Supports rich staff format: [{name, orcid, department, faculty}]
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class InstitutionConfig:
    """Configuration for a single institution"""

    def __init__(
        self,
        ror,
        name,
        short_name,
        country,
        staff_file,
        affiliation_patterns,
        faculties=None,
        crawler_settings=None,
        sub_region="Unknown",
    ):
        self.ror = ror
        self.name = name
        self.short_name = short_name
        self.country = country
        self.staff_file = staff_file
        self.affiliation_patterns = affiliation_patterns
        self.faculties = faculties or []
        self.crawler_settings = crawler_settings or {}
        self.sub_region = sub_region
        self._raw_staff: List[Any] = self._load_staff_raw()

    def _resolve_staff_file(self) -> str:
        if os.path.isabs(self.staff_file):
            return self.staff_file
        base_dir = Path(__file__).parent.parent.parent
        candidate = base_dir / self.staff_file
        if candidate.exists():
            return str(candidate)
        if os.path.exists(self.staff_file):
            return self.staff_file
        return str(candidate)

    def _load_staff_raw(self) -> List[Any]:
        path = self._resolve_staff_file()
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                if "staff" in data:
                    return data["staff"]
                if "names" in data:
                    return data["names"]
                names = []
                for value in data.values():
                    if isinstance(value, list):
                        names.extend(value)
                return names
            return []
        except Exception as e:
            print(f"Warning: Error loading staff file {path}: {e}")
            return []

    @property
    def staff_names(self) -> List[str]:
        """Flat list of staff names (backwards compatible)."""
        names = []
        for entry in self._raw_staff:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict):
                n = entry.get("name") or entry.get("display_name", "")
                if n:
                    names.append(n)
        return names

    @property
    def staff_records(self) -> List[Dict]:
        """Rich staff records: [{name, orcid, department, faculty}]."""
        records = []
        for entry in self._raw_staff:
            if isinstance(entry, str):
                records.append(
                    {"name": entry, "orcid": None, "department": None, "faculty": None}
                )
            elif isinstance(entry, dict):
                records.append(
                    {
                        "name": entry.get("name") or entry.get("display_name", ""),
                        "orcid": entry.get("orcid"),
                        "department": entry.get("department"),
                        "faculty": entry.get("faculty"),
                        "openalex_id": entry.get("openalex_id"),
                        "paper_count": entry.get("paper_count", 0),
                    }
                )
        return [r for r in records if r["name"]]

    @property
    def staff_with_orcid(self) -> List[Dict]:
        return [r for r in self.staff_records if r.get("orcid")]

    @property
    def departments(self) -> List[str]:
        depts = set()
        for r in self.staff_records:
            if r.get("department"):
                depts.add(r["department"])
        return sorted(depts)

    def matches_affiliation(self, affiliation_text: str) -> bool:
        if not affiliation_text:
            return False
        affiliation_lower = affiliation_text.lower()
        return any(p.lower() in affiliation_lower for p in self.affiliation_patterns)

    def verify_ror_in_authorships(self, authorships: List[Dict]) -> bool:
        """
        Verify at least one author has this institution's ROR.
        Critical gate for 98% precision crawling.
        """
        if not authorships:
            return False
        target_short = self.ror.split("/")[-1]
        for authorship in authorships:
            for inst in authorship.get("institutions", []):
                inst_ror = inst.get("ror", "") or inst.get("id", "") or ""
                if target_short in inst_ror or self.ror == inst_ror:
                    return True
        return False

    def to_dict(self) -> Dict:
        return {
            "ror": self.ror,
            "name": self.name,
            "short_name": self.short_name,
            "country": self.country,
            "staff_file": self.staff_file,
            "affiliation_patterns": self.affiliation_patterns,
            "faculties": self.faculties,
            "crawler_settings": self.crawler_settings,
            "sub_region": self.sub_region,
            "staff_count": len(self.staff_names),
            "staff_with_orcid_count": len(self.staff_with_orcid),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "InstitutionConfig":
        sub_region = data.get("sub_region")
        if not sub_region:
            country = data.get("country", "")
            if country in ("Nigeria", "Ghana"):
                sub_region = "West Africa"
            elif country in (
                "South Africa",
                "Zimbabwe",
                "Zambia",
                "Namibia",
                "Botswana",
                "Lesotho",
                "Eswatini",
                "Malawi",
                "Mozambique",
            ):
                sub_region = "Southern Africa"
            elif country in ("Kenya", "Uganda", "Ethiopia", "Rwanda", "Tanzania"):
                sub_region = "East Africa"
            elif country in (
                "Egypt",
                "Morocco",
                "Tunisia",
                "Algeria",
                "Libya",
                "Sudan",
            ):
                sub_region = "North Africa"
            elif country in (
                "Cameroon",
                "DR Congo",
                "Angola",
                "Gabon",
                "Republic of the Congo",
            ):
                sub_region = "Central Africa"
            else:
                sub_region = "Unknown"
        return cls(
            ror=data["ror"],
            name=data["name"],
            short_name=data["short_name"],
            country=data["country"],
            staff_file=data["staff_file"],
            affiliation_patterns=data["affiliation_patterns"],
            faculties=data.get("faculties", []),
            crawler_settings=data.get("crawler_settings", {}),
            sub_region=sub_region,
        )

    @classmethod
    def from_json_file(cls, file_path: str) -> "InstitutionConfig":
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


class InstitutionRegistry:
    """Registry of all configured institutions"""

    def __init__(self, config_dir: str = None):
        if config_dir is None:
            base_dir = Path(__file__).parent.parent.parent
            config_dir = base_dir / "config" / "institutions"
        self.config_dir = Path(config_dir)
        self.institutions: Dict[str, InstitutionConfig] = {}
        self._load_all_institutions()

    def _load_all_institutions(self):
        if not self.config_dir.exists():
            print(f"Warning: Institution config directory not found: {self.config_dir}")
            return
        for json_file in sorted(self.config_dir.glob("*.json")):
            try:
                config = InstitutionConfig.from_json_file(str(json_file))
                self.institutions[config.short_name.lower()] = config
            except Exception as e:
                print(f"Error loading {json_file}: {e}")

    def get(self, identifier: str) -> Optional[InstitutionConfig]:
        identifier_lower = identifier.lower()
        if identifier_lower in self.institutions:
            return self.institutions[identifier_lower]
        for config in self.institutions.values():
            if (
                config.ror == identifier
                or identifier_lower == config.ror.split("/")[-1]
            ):
                return config
        return None

    def get_by_ror(self, ror: str) -> Optional[InstitutionConfig]:
        for config in self.institutions.values():
            if config.ror == ror:
                return config
        return None

    def list_all(self) -> List[InstitutionConfig]:
        return list(self.institutions.values())

    def list_by_country(self, country: str) -> List[InstitutionConfig]:
        return [
            c
            for c in self.institutions.values()
            if c.country.lower() == country.lower()
        ]

    def add_institution(self, config: InstitutionConfig):
        self.institutions[config.short_name.lower()] = config

    def save_institution(self, config: InstitutionConfig):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.config_dir / f"{config.short_name.lower()}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
        self.add_institution(config)


_registry = None


def get_registry() -> InstitutionRegistry:
    global _registry
    if _registry is None:
        _registry = InstitutionRegistry()
    return _registry


def reset_registry():
    global _registry
    _registry = None
