"""Database models package.

Exports all models for easy importing throughout the application.

Importing model modules here ensures their tables are registered on the shared
``db`` metadata so both ``db.create_all()`` (tests) and Alembic autogenerate
can see them.
"""
from .base import db
from .repository_analysis import RepositoryAnalysis

__all__ = ['db', 'RepositoryAnalysis']
