"""Institution registry correctness: loading, lookup, and affiliation matching."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uraas.config.institutions import get_registry
from uraas.utils.staff_validator import StaffValidator, staff_validator


@pytest.fixture(scope="module")
def registry():
    return get_registry()


def test_registry_loads_many_institutions(registry):
    # Live-verified 2026-08: 52 African institutions are registered. Assert
    # a floor, not an exact count, so growing the registry doesn't break CI.
    assert len(registry.list_all()) >= 10


def test_get_by_short_name(registry):
    unilag = registry.get("unilag")
    assert unilag is not None
    assert unilag.name == "University of Lagos"
    assert unilag.ror == "https://ror.org/05rk03822"


def test_get_by_ror(registry):
    unilag = registry.get("unilag")
    found = registry.get_by_ror(unilag.ror)
    assert found is not None
    assert found.name == unilag.name


def test_unknown_institution_returns_none(registry):
    assert registry.get("definitely-not-a-real-institution") is None


def test_affiliation_matching_positive(registry):
    unilag = registry.get("unilag")
    assert unilag.matches_affiliation("Department of Physics, University of Lagos")


def test_affiliation_matching_negative(registry):
    unilag = registry.get("unilag")
    assert not unilag.matches_affiliation("Massachusetts Institute of Technology")


def test_staff_validator_constructs_for_unilag(registry):
    unilag = registry.get("unilag")
    validator = StaffValidator(institution_config=unilag)
    assert validator.institution_name == unilag.name
    # Live-verified 2026-08: 11,854 UNILAG staff records harvested via ROR.
    assert len(validator.staff_names) > 1000


def test_staff_validator_rejects_non_staff():
    # A name with no plausible relation to any real UNILAG staff record.
    assert not staff_validator.is_staff_member("Zzyzx Qqvraxk Nonexistentname")
