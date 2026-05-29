"""
Simple script to start the URAAS dashboard.
Handles Python path setup automatically.
"""

import os
import sys

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Now import and run the dashboard
import uraas

print(f"DEBUG: uraas path: {uraas.__path__}", flush=True)
from uraas.config import config
from uraas.dashboard.app import app, socketio

if __name__ == "__main__":
    print("=" * 70, flush=True)
    print("URAAS Dashboard Starting...", flush=True)
    print("=" * 70, flush=True)
    print(f"Dashboard URL: http://localhost:{config.DASHBOARD_PORT}", flush=True)
    print("Press Ctrl+C to stop", flush=True)
    print("=" * 70, flush=True)
    socketio.run(
        app,
        host="0.0.0.0",
        port=config.DASHBOARD_PORT,
        debug=False,
        allow_unsafe_werkzeug=True,
    )
