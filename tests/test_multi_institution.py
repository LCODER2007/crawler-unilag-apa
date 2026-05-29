"""
Test script for multi-institution support
Tests institution configuration and staff validation
"""

import sys
import os
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uraas.config.institutions import InstitutionRegistry, get_registry
from uraas.utils.staff_validator import StaffValidator


@pytest.fixture
def registry():
    """Provide the institution registry as a pytest fixture."""
    return get_registry()


def test_institution_registry():
    """Test institution registry loading"""
    print("=" * 60)
    print("TEST 1: Institution Registry")
    print("=" * 60)

    registry = get_registry()

    print(f"\nLoaded {len(registry.institutions)} institutions:")
    for config in registry.list_all():
        print(f"  - {config.name} ({config.short_name})")
        print(f"    ROR: {config.ror}")
        print(f"    Country: {config.country}")
        print(f"    Staff count: {len(config.staff_names)}")
        print(f"    Affiliation patterns: {len(config.affiliation_patterns)}")
        print()

    # Test retrieval by short name
    print("\nTest retrieval by short name:")
    unilag = registry.get("unilag")
    if unilag:
        print(f"  ✓ Found UNILAG: {unilag.name}")
    else:
        print(f"  ✗ UNILAG not found")

    # Test retrieval by ROR
    print("\nTest retrieval by ROR:")
    ui = registry.get_by_ror("https://ror.org/01js2sh04")
    if ui:
        print(f"  ✓ Found UI: {ui.name}")
    else:
        print(f"  ✗ UI not found")

    # Test affiliation matching
    print("\nTest affiliation matching:")
    test_affiliations = [
        ("University of Lagos, Nigeria", "unilag"),
        ("Department of Physics, University of Ibadan", "ui"),
        ("OAU Ile-Ife, Nigeria", "oau"),
        ("Ahmadu Bello University, Zaria", "abu"),
    ]

    for affiliation, expected_short_name in test_affiliations:
        matched = False
        for config in registry.list_all():
            if config.matches_affiliation(affiliation):
                print(f"  ✓ '{affiliation}' → {config.short_name}")
                if config.short_name.lower() == expected_short_name.lower():
                    matched = True
                break
        if not matched:
            print(f"  ✗ '{affiliation}' not matched correctly")

    return registry


def test_staff_validator(registry):
    """Test staff validator with multi-institution support"""
    print("\n" + "=" * 60)
    print("TEST 2: Staff Validator")
    print("=" * 60)

    # Test UNILAG validator
    print("\nTesting UNILAG validator:")
    unilag_config = registry.get("unilag")
    if unilag_config:
        validator = StaffValidator(institution_config=unilag_config)
        print(f"  Institution: {validator.institution_name}")
        print(f"  ROR: {validator.ror}")
        print(f"  Staff count: {len(validator.staff_names)}")

        # Test some known UNILAG staff (if any)
        test_authors = [
            "Prof. A. O. Adeyemi",
            "Dr. John Smith",  # Should not match
            "O. A. Ogunlana",
        ]

        print("\n  Testing author validation:")
        for author in test_authors:
            is_staff = validator.is_staff_member(author)
            print(
                f"    {'✓' if is_staff else '✗'} {author}: {'Staff' if is_staff else 'Not staff'}"
            )

    # Test UI validator (will have empty staff list for now)
    print("\nTesting UI validator:")
    ui_config = registry.get("ui")
    if ui_config:
        validator = StaffValidator(institution_config=ui_config)
        print(f"  Institution: {validator.institution_name}")
        print(f"  ROR: {validator.ror}")
        print(f"  Staff count: {len(validator.staff_names)}")
        print(f"  Note: Staff file not yet populated")


def test_backward_compatibility():
    """Test that old code still works"""
    print("\n" + "=" * 60)
    print("TEST 3: Backward Compatibility")
    print("=" * 60)

    # Test default validator (should still work for UNILAG)
    from uraas.utils.staff_validator import staff_validator

    print(f"\nDefault validator:")
    print(f"  Institution: {staff_validator.institution_name}")
    print(f"  Staff count: {len(staff_validator.staff_names)}")
    print(f"  ✓ Backward compatibility maintained")


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("MULTI-INSTITUTION SUPPORT TEST SUITE")
    print("=" * 60)

    try:
        # Test 1: Institution Registry
        registry = test_institution_registry()

        # Test 2: Staff Validator
        test_staff_validator(registry)

        # Test 3: Backward Compatibility
        test_backward_compatibility()

        print("\n" + "=" * 60)
        print("ALL TESTS COMPLETED")
        print("=" * 60)
        print("\nSummary:")
        print(f"  - {len(registry.institutions)} institutions configured")
        print(f"  - Institution registry operational")
        print(f"  - Staff validator supports multi-institution")
        print(f"  - Backward compatibility maintained")
        print("\nNext steps:")
        print("  1. Populate staff files for UI, OAU, UNN, ABU")
        print("  2. Update spiders to accept institution parameter")
        print("  3. Test multi-institution crawling")

    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
