"""
Staff Validator - Validates authors against institution staff lists.
Supports multi-institution with ROR-based configuration.
"""

import os
import json
import re
import logging
from typing import List, Set, Optional, Dict, Tuple
from thefuzz import fuzz

logger = logging.getLogger(__name__)


class StaffValidator:
    """
    Validates authors against institution staff lists.
    Now supports multiple institutions via InstitutionConfig.
    """

    def __init__(self, institution_config=None, staff_cache_path: str = None):
        """
        Initialize validator with institution configuration.

        Args:
            institution_config: InstitutionConfig object (new multi-institution support)
            staff_cache_path: Legacy path to staff JSON (for backward compatibility)
        """
        self.institution_config = institution_config

        # Determine staff file path
        if institution_config:
            self.staff_cache_path = institution_config.staff_file
            self.institution_name = institution_config.name
            self.ror = institution_config.ror
        elif staff_cache_path:
            self.staff_cache_path = staff_cache_path
            self.institution_name = "Unknown"
            self.ror = None
        else:
            # Default to UNILAG for backward compatibility
            self.staff_cache_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "data", "unilag_staff.json"
            )
            self.institution_name = "University of Lagos"
            self.ror = "https://ror.org/05rk03822"

        self.staff_names: Set[str] = set()
        self.normalized_staff: Set[str] = set()
        self._faculty_map: Dict[str, List[str]] = {}
        self._surname_to_faculty: Dict[str, str] = {}
        self._surname_to_dept: Dict[str, str] = {}
        self._fullname_to_faculty: Dict[str, str] = {}
        self._fullname_to_dept: Dict[str, str] = {}
        self._detailed_records: List = []

        self.load_staff_cache()
        self._load_faculty_map()

    def load_staff_cache(self):
        """Load staff names from JSON file"""
        if not os.path.exists(self.staff_cache_path):
            logger.warning(f"Staff file not found: {self.staff_cache_path}")
            return

        try:
            with open(self.staff_cache_path, "r", encoding="utf-8") as f:
                staff_data = json.load(f)

            # Handle different JSON structures
            if isinstance(staff_data, list):
                staff_list = staff_data
            elif isinstance(staff_data, dict):
                # Extract names from various possible structures
                if "staff" in staff_data:
                    staff_list = staff_data["staff"]
                elif "names" in staff_data:
                    staff_list = staff_data["names"]
                else:
                    # Flatten all values that are lists
                    staff_list = []
                    for value in staff_data.values():
                        if isinstance(value, list):
                            staff_list.extend(value)
            else:
                staff_list = []

            for entry in staff_list:
                # Each entry may be a plain string or a dict with a 'name' key
                if isinstance(entry, dict):
                    name = entry.get("name", "")
                elif isinstance(entry, str):
                    name = entry
                else:
                    continue
                cleaned = self._clean_name(name)
                if cleaned:
                    self.staff_names.add(cleaned)
                    self.normalized_staff.add(self._normalize_name(cleaned))

            logger.info(
                f"Loaded {len(self.staff_names)} staff members for {self.institution_name}"
            )

        except Exception as e:
            logger.error(f"Error loading staff cache from {self.staff_cache_path}: {e}")

    def _load_faculty_map(self):
        """Load faculty and department mappings"""
        # Try to load detailed staff records (name → faculty/dept)
        base_name = os.path.splitext(os.path.basename(self.staff_cache_path))[0]
        detailed_path = os.path.join(
            os.path.dirname(self.staff_cache_path), f"{base_name}_detailed.json"
        )

        if os.path.exists(detailed_path):
            try:
                with open(detailed_path, "r", encoding="utf-8") as f:
                    records = json.load(f)
                self._detailed_records = records
                self._surname_to_faculty: Dict[str, str] = {}
                self._surname_to_dept: Dict[str, str] = {}
                self._fullname_to_faculty: Dict[str, str] = {}
                self._fullname_to_dept: Dict[str, str] = {}

                for r in records:
                    name = r.get("name", "")
                    faculty = r.get("faculty", "Unknown")
                    dept = r.get("department", "Unknown")
                    if not name or faculty == "Unknown":
                        continue

                    # Store full normalized name lookup (most accurate)
                    norm = self._normalize_name(self._clean_name(name))
                    if norm:
                        self._fullname_to_faculty[norm] = faculty
                        if dept != "Unknown":
                            self._fullname_to_dept[norm] = dept

                    # Store surname (last word) lookup as fallback
                    parts = name.strip().split()
                    if parts:
                        surname = re.sub(r"[^\w]", "", parts[-1].lower())
                        if len(surname) >= 4:
                            # Only set if not already set (first match wins)
                            if surname not in self._surname_to_faculty:
                                self._surname_to_faculty[surname] = faculty
                            if (
                                dept != "Unknown"
                                and surname not in self._surname_to_dept
                            ):
                                self._surname_to_dept[surname] = dept
                return
            except Exception as e:
                logger.warning(f"Could not load detailed staff records: {e}")

        # Fallback: keyword map (UNILAG-specific, may not exist for other institutions)
        self._detailed_records = []
        self._surname_to_faculty = {}
        self._surname_to_dept = {}
        self._fullname_to_faculty = {}
        self._fullname_to_dept = {}

        map_path = os.path.join(
            os.path.dirname(self.staff_cache_path), "staff_department_map.json"
        )
        if os.path.exists(map_path):
            try:
                with open(map_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._faculty_map = {
                    faculty: data.get("keywords", []) for faculty, data in raw.items()
                }
            except Exception:
                pass

    def _clean_name(self, name: str) -> str:
        """Remove titles and degrees from name"""
        name = re.sub(
            r"\b(Prof\.?|Dr\.?|Mr\.?|Mrs\.?|Miss\.?|Ms\.?|Engr\.?|Pharm\.?|Assoc\.?|Associate)\s*",
            "",
            name,
            flags=re.IGNORECASE,
        )
        name = re.sub(
            r"\b(Ph\.?D\.?|M\.?Sc\.?|B\.?Sc\.?|M\.?B\.?,?\s*B\.?S\.?|M\.?Phil\.?)\s*",
            "",
            name,
            flags=re.IGNORECASE,
        )
        name = re.sub(r"\(Mrs\.?\)|(\(Mr\.?\))", "", name)
        name = re.sub(r"[,\.]", "", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name

    def _normalize_name(self, name: str) -> str:
        """Normalize name for comparison"""
        name = name.lower()
        name = re.sub(r"[^\w\s]", "", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name

    def is_staff_member(self, author_name: str, fuzzy_threshold: int = 75) -> bool:
        """Check if author is a staff member of this institution"""
        if not author_name:
            return False

        # If no staff directory loaded, bypass and rely on ROR and affiliation gates
        if not self.normalized_staff:
            return True

        cleaned = self._clean_name(author_name)
        normalized = self._normalize_name(cleaned)

        # Exact match
        if normalized in self.normalized_staff:
            return True

        # Fuzzy match
        for staff_name in self.normalized_staff:
            if fuzz.ratio(normalized, staff_name) >= fuzzy_threshold:
                return True

        return False

    def get_faculty_hint(self, author_name: str) -> Optional[str]:
        """Return most likely faculty — checks full name first, then surname."""
        if not author_name:
            return None

        # 1. Full normalized name lookup (most accurate)
        norm = self._normalize_name(self._clean_name(author_name))
        if norm in self._fullname_to_faculty:
            return self._fullname_to_faculty[norm]

        # 2. Fuzzy match against full name lookup
        from thefuzz import process

        if self._fullname_to_faculty:
            match = process.extractOne(
                norm, self._fullname_to_faculty.keys(), score_cutoff=80
            )
            if match:
                return self._fullname_to_faculty[match[0]]

        # 3. Surname fallback
        parts = author_name.strip().split()
        if parts:
            surname = re.sub(r"[^\w]", "", parts[-1].lower())
            if surname in self._surname_to_faculty:
                return self._surname_to_faculty[surname]

        # 4. Keyword map fallback
        for part in author_name.lower().split():
            part = re.sub(r"[^\w]", "", part)
            if len(part) < 4:
                continue
            for faculty, keywords in self._faculty_map.items():
                if any(part in kw or kw in part for kw in keywords):
                    return faculty

        return None

    def get_department_hint(self, author_name: str) -> Optional[str]:
        """Return most likely department."""
        if not author_name:
            return None

        norm = self._normalize_name(self._clean_name(author_name))
        if norm in self._fullname_to_dept:
            return self._fullname_to_dept[norm]

        from thefuzz import process

        if self._fullname_to_dept:
            match = process.extractOne(
                norm, self._fullname_to_dept.keys(), score_cutoff=80
            )
            if match:
                return self._fullname_to_dept[match[0]]

        parts = author_name.strip().split()
        if parts:
            surname = re.sub(r"[^\w]", "", parts[-1].lower())
            if surname in self._surname_to_dept:
                return self._surname_to_dept[surname]

        return None

    def get_all_faculty_hints(self, authors: List[str]) -> List[Tuple[str, str]]:
        """
        Returns (author, faculty) pairs for all confirmed staff authors.
        Handles multiple staff authors on the same paper.
        """
        results = []
        for author in authors:
            if self.is_staff_member(author, fuzzy_threshold=75):
                hint = self.get_faculty_hint(author)
                if hint:
                    results.append((author, hint))
        return results

    def validate_authors(self, authors: List[str], require_all: bool = False) -> bool:
        """Validate if authors include staff members"""
        if not authors:
            return False
        matches = [self.is_staff_member(a) for a in authors]
        return all(matches) if require_all else any(matches)

    def get_matching_staff(self, authors: List[str]) -> List[str]:
        """Get list of authors who are staff members"""
        return [a for a in authors if self.is_staff_member(a)]


# Global instance (backward compatibility - defaults to UNILAG)
staff_validator = StaffValidator()
