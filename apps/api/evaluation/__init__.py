"""Offline evaluation.

Like `ingestion`, this package is deliberately outside `app`: it reads ground truth, and
nothing that serves a request may. It depends on `app.triage` to run inference — the
direction is one-way, and a test enforces it.
"""
