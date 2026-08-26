"""Offline ingestion of external datasets.

This package is deliberately separate from `app`: it runs from scripts, never inside a
request. The runtime API must not import it, and a test enforces that — external
evaluation data has no business being reachable from a serving code path.
"""
