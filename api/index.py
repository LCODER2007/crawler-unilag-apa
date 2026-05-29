import os
import sys

# Add root directory to sys.path so 'uraas' package is findable
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set environment variables for Vercel
# Vercel filesystem is read-only, so we point SQLite to a temp dir if we want to write,
# or just keep it in the project root if it's read-only.
os.environ["DATABASE_URL"] = "sqlite:///uraas.db"

from uraas.dashboard.app import app

# For Vercel, the variable must be named 'app'
# but since we imported 'app' from uraas.dashboard.app, it's already there.
# We just need to make sure it's exported at the module level.
handler = app
