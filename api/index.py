"""
Vercel Serverless Function Entry Point for BloodConnect Flask Application.
Exposes the WSGI `app` callable to Vercel's Python runtime.
"""

import sys
import os

# Add root directory to sys.path so modules (app, database, qr_service) can be resolved
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app import app
