"""Investigation constants."""

INVESTIGATION_VERSION = "investigation-v1"

# How many historical precedents are put in front of the model. Three is enough to show
# a pattern without letting a wall of loosely-similar past incidents crowd out the
# operational signals, which are the evidence that actually distinguishes causes.
HISTORICAL_EVIDENCE_K = 3
