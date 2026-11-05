"""Vercel's entry point. vercel.json sends every /api/ request here, and the app sees the original path."""
from creed.api.app import app

__all__ = ["app"]
