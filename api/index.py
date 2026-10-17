"""Vercel entrypoint: serves the FastAPI app from jyotisha_council/api.py at /api/*."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jyotisha_council"))

from api import app  # noqa: E402,F401  (jyotisha_council/api.py)
