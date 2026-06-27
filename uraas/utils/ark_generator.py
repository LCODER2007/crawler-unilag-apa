"""
ARK (Archival Resource Key) generator for URAAS.

ARKs are free, decentralised persistent identifiers (arks.org). The Africa
PID Alliance partnered with the ARK Alliance (March 2025) to strengthen PID
infrastructure in Africa — URAAS mints an ARK for every item alongside its
DocID™ so outputs without DOIs still carry a resolvable persistent ID.

Format: ark:/<NAAN>/<shoulder><name><check>
- NAAN: Name Assigning Authority Number (env ARK_NAAN; 99999 = official
  test NAAN until the production registration completes).
- shoulder: sub-namespace (env ARK_SHOULDER, default "u1").
- name: 12 betanumeric chars derived deterministically from the seed
  (the item's DocID hash), so re-minting is idempotent.
- check: NCDA (Noid Check Digit Algorithm) character.
"""

import hashlib
import re

from uraas.config import config

# Betanumeric alphabet (NOID's "extended digits"): digits + consonants,
# excluding vowels and 'l' to avoid accidental words and misreads.
BETANUMERIC = "0123456789bcdfghjkmnpqrstvwxz"

_ARK_RE = re.compile(r"^ark:/(\d{5,9})/([" + BETANUMERIC + r"]+)$")


class ARKGenerator:
    """Mint and validate ARK identifiers (deterministic from a seed)."""

    @property
    def naan(self) -> str:
        return config.ARK_NAAN

    @property
    def shoulder(self) -> str:
        return config.ARK_SHOULDER

    @classmethod
    def _check_char(cls, naan: str, name: str) -> str:
        """NCDA check character over the NAAN + name portion.

        Each char maps to its betanumeric ordinal (non-betanumeric chars
        count as 0), weighted by 1-based position; sum mod 29 indexes the
        alphabet (the standard NOID checkchar algorithm)."""
        s = f"{naan}/{name}"
        total = 0
        for pos, ch in enumerate(s, start=1):
            total += BETANUMERIC.find(ch) * pos if ch in BETANUMERIC else 0
        return BETANUMERIC[total % len(BETANUMERIC)]

    def mint(self, seed: str) -> str:
        """Deterministically mint an ARK from a seed string (the item DocID).

        Same seed → same ARK, so backfills are idempotent."""
        digest = hashlib.sha256((seed or "").encode("utf-8")).digest()
        # Map hash bytes onto the betanumeric alphabet for a 12-char name.
        body = "".join(BETANUMERIC[b % len(BETANUMERIC)] for b in digest[:12])
        name = f"{self.shoulder}{body}"
        return f"ark:/{self.naan}/{name}{self._check_char(self.naan, name)}"

    @classmethod
    def validate(cls, ark: str) -> bool:
        m = _ARK_RE.match(ark or "")
        if not m:
            return False
        naan, full_name = m.groups()
        if len(full_name) < 4:
            return False
        name, check = full_name[:-1], full_name[-1]
        return cls._check_char(naan, name) == check

    @staticmethod
    def to_url(ark: str) -> str:
        """Local resolver path (ARK spec: resolver base + '/' + ark)."""
        return f"/{ark}"


ark_generator = ARKGenerator()
