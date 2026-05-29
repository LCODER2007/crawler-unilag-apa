import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging

from uraas.analytics.engine import URAASAnalyticsEngine

logging.basicConfig(level=logging.DEBUG)

analytics = URAASAnalyticsEngine()

print("Testing get_publications_by_year...")
try:
    res = analytics.get_publications_by_year()
    print("Result:", res)
except Exception as e:
    print("Error in get_publications_by_year:", e)
    import traceback

    traceback.print_exc()

print("\nTesting get_institutional_growth...")
try:
    res = analytics.get_institutional_growth()
    print("Result:", res)
except Exception as e:
    print("Error in get_institutional_growth:", e)
    import traceback

    traceback.print_exc()
