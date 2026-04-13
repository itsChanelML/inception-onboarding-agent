"""
api/index.py — Vercel serverless entry point.
Imports the Flask app from app.py and exposes it as `handler`.
Vercel detects the `handler` variable automatically.
"""

import sys
import os

# Ensure the project root is on the path so app.py can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# Vercel looks for a variable named `handler`
handler = app