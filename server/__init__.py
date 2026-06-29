"""AIECO Dashboard backend server.

FastAPI + SQLite backend that ingests employee AI usage metrics from edge
collectors, aggregates them, computes training and plan recommendations,
and serves APIs for a management dashboard.
"""

__version__ = "0.1.0"
