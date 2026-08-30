"""Gunicorn entry point for the container deployment."""
from .web import create_app

app = create_app()
