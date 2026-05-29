"""
DocID Generator for URAAS
Implements the Africa PID Alliance DocID™ persistent identifier system.

DocID Format: 20.500.14351/[unique-hash]
- 20.500.14351 is the APA Handle prefix
- Unique hash ensures global uniqueness and long-term accessibility
"""

import hashlib
import uuid
from datetime import datetime
from typing import Dict, Optional


class DocIDGenerator:
    """
    Generate DocID™ persistent identifiers following Africa PID Alliance standards.

    DocID™ is a persistent identifier (PID) system developed by TCC Africa and
    the Africa PID Alliance to secure African research outputs, indigenous knowledge,
    and cultural heritage.
    """

    # APA Handle prefix for Africa PID Alliance
    APA_HANDLE_PREFIX = "20.500.14351"

    # Supported identifier types
    IDENTIFIER_TYPES = [
        "DOCiD",  # Internal identifier format
        "APA Handle ID",  # African PID Alliance Handle Service
        "DOI",  # Digital Object Identifier
        "Handle",  # Handle System identifier
        "ARK",  # Archival Resource Key
        "URN",  # Uniform Resource Name
        "ORCID",  # Creator identification
        "ROR",  # Organization identification
    ]

    @classmethod
    def generate_docid(
        cls,
        title: str,
        doi: Optional[str] = None,
        institution: str = "University of Lagos",
        timestamp: Optional[datetime] = None,
    ) -> str:
        """
        Generate a unique DocID™ identifier.

        Args:
            title: Publication title
            doi: Existing DOI (if available)
            institution: Institution name
            timestamp: Publication timestamp (defaults to now)

        Returns:
            DocID in format: 20.500.14351/[unique-hash]
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        # Create unique string from multiple sources
        unique_string = (
            f"{title}|{doi or ''}|{institution}|{timestamp.isoformat()}|{uuid.uuid4()}"
        )

        # Generate SHA-256 hash and take first 20 characters for readability
        hash_object = hashlib.sha256(unique_string.encode("utf-8"))
        unique_hash = hash_object.hexdigest()[:20]

        # Return DocID in APA Handle format
        return f"{cls.APA_HANDLE_PREFIX}/{unique_hash}"

    @classmethod
    def generate_docid_metadata(cls, paper_data: Dict) -> Dict:
        """
        Generate complete DocID™ metadata package for a publication.

        Args:
            paper_data: Dictionary containing paper information

        Returns:
            Dictionary with DocID and associated metadata
        """
        docid = cls.generate_docid(
            title=paper_data.get("title", "Untitled"),
            doi=paper_data.get("doi"),
            institution=paper_data.get("institution", "University of Lagos"),
            timestamp=paper_data.get("publication_date"),
        )

        metadata = {
            # Primary identifier
            "document_docid": docid,
            "docid_assigned_date": datetime.utcnow().isoformat(),
            # Identifier type
            "identifier_type": "APA Handle ID",
            "identifier_scheme": "Handle",
            # Alternate identifiers
            "alternate_identifiers": [],
            # Metadata
            "title": paper_data.get("title"),
            "institution": paper_data.get("institution", "University of Lagos"),
            "institution_ror": "https://ror.org/05rk03822",  # UNILAG ROR ID
            # Provenance
            "source_repository": paper_data.get(
                "source_repository", "UNILAG Institutional Repository"
            ),
            "source_url": paper_data.get("url"),
            # Handle resolution URL
            "handle_url": f"https://hdl.handle.net/{docid}",
            "docid_url": f"https://docid.africapidalliance.org/resolve/{docid}",
        }

        # Add DOI as alternate identifier if present
        if paper_data.get("doi"):
            metadata["alternate_identifiers"].append(
                {"type": "DOI", "value": paper_data["doi"], "is_primary": False}
            )

        # Add ORCID for authors if available
        if paper_data.get("authors"):
            for author in paper_data["authors"]:
                if author.get("orcid"):
                    metadata["alternate_identifiers"].append(
                        {"type": "ORCID", "value": author["orcid"], "role": "Creator"}
                    )

        return metadata

    @classmethod
    def validate_docid(cls, docid: str) -> bool:
        """
        Validate a DocID™ identifier format.

        Args:
            docid: DocID string to validate

        Returns:
            True if valid, False otherwise
        """
        if not docid:
            return False

        parts = docid.split("/")
        if len(parts) != 2:
            return False

        prefix, hash_part = parts

        # Check prefix matches APA Handle
        if prefix != cls.APA_HANDLE_PREFIX:
            return False

        # Check hash part is alphanumeric and reasonable length
        if not hash_part or not hash_part.isalnum():
            return False

        if len(hash_part) < 10 or len(hash_part) > 64:
            return False

        return True

    @classmethod
    def format_citation_with_docid(cls, paper_data: Dict, docid: str) -> str:
        """
        Format a citation including the DocID™ identifier.

        Args:
            paper_data: Paper metadata
            docid: DocID identifier

        Returns:
            Formatted citation string
        """
        authors = paper_data.get("authors", [])
        author_str = ", ".join([a.get("name", "") for a in authors[:3]])
        if len(authors) > 3:
            author_str += " et al."

        title = paper_data.get("title", "Untitled")

        # Handle both string and datetime objects for publication_date
        pub_date = paper_data.get("publication_date")
        if isinstance(pub_date, datetime):
            year = pub_date.year
        elif isinstance(pub_date, str):
            year = pub_date.split("-")[0] if pub_date else "n.d."
        else:
            year = "n.d."

        citation = f"{author_str} ({year}). {title}. "
        citation += f"University of Lagos Institutional Repository. "
        citation += f"DocID: {docid}. "
        citation += f"Available at: https://hdl.handle.net/{docid}"

        return citation


# Singleton instance
docid_generator = DocIDGenerator()
