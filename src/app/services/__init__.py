"""Services package for the /learn codebase-learning feature.

Business logic (URL parsing, GitHub access, heuristic analysis) lives here so
the Flask views stay thin and everything is unit-testable without a request
context. The existing ``controllers/`` package is intentionally left unused.
"""
