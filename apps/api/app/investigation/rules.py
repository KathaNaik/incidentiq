"""Investigation constants."""

INVESTIGATION_VERSION = "investigation-v1"

# How many historical precedents are put in front of the model. Three is enough to show
# a pattern without letting a wall of loosely-similar past incidents crowd out the
# operational signals, which are the evidence that actually distinguishes causes.
HISTORICAL_EVIDENCE_K = 3

# The shape of the evidence an investigation was given.
#
# This is versioned separately from the prompt on purpose. M14 changed what the model
# *sees* — chronological observations plus derived temporal relationships — without
# changing the prompt at all, and a metric measured under one evidence schema is not
# comparable to a metric measured under another. Conflating "the evidence improved" with
# "the prompt improved" would make both unmeasurable.
EVIDENCE_SCHEMA_V1 = "evidence-v1"
"""Observations only. No derived chronology. Everything recorded before M14."""

EVIDENCE_SCHEMA_V2 = "evidence-v2"
"""Adds ordered health history, incident onset, temporal relationships, and deployment
attribution as citable evidence."""

CURRENT_EVIDENCE_SCHEMA = EVIDENCE_SCHEMA_V2
