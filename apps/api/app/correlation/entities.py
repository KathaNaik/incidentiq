"""Identifier extraction from raw ticket text.

Deliberately runs on the *raw* string rather than the normalized one: case and
punctuation are exactly what makes `ERR_AUTH_17`, `GA4` and `us-east-1` recognisable,
and normalization folds them away. This is not a second copy of the triage vocabulary —
triage asks "what kind of problem is this", these patterns ask "which specific thing is
being named".
"""

import re

from pydantic import BaseModel, ConfigDict

# Order matters only for readability; every pattern is applied to the whole text.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # ERR_AUTH_17, IKE_SA, E_TIMEOUT-3
    ("error_code", re.compile(r"\b[A-Z][A-Z0-9]{1,}(?:[_-][A-Z0-9]+)+\b")),
    # HTTP status codes in the 4xx/5xx families.
    ("http_status", re.compile(r"\b[45]\d{2}\b")),
    # us-east-1, eu-west-2
    ("region", re.compile(r"\b[a-z]{2}-[a-z]+-\d\b")),
    # /api/v2/reports
    ("endpoint", re.compile(r"(?<![\w.])/[a-z0-9][a-z0-9/_-]{2,}")),
    # sso.northstar.example, dc-east-03.internal
    ("host", re.compile(r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+\.[a-z]{2,}\b")),
    # GA4, S3, EU2, v2 — short alphanumeric product names.
    ("identifier", re.compile(r"\b[A-Z][A-Za-z]{0,4}\d{1,3}\b")),
)


class Entity(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    value: str


def extract_entities(text: str) -> tuple[Entity, ...]:
    """Finds named identifiers in ticket text, deduplicated and ordered."""
    found: set[Entity] = set()
    for kind, pattern in PATTERNS:
        for match in pattern.findall(text or ""):
            found.add(Entity(kind=kind, value=match.lower()))
    return tuple(sorted(found, key=lambda entity: (entity.kind, entity.value)))
