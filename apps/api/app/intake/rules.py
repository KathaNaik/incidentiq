"""Intake configuration, in one place.

Two windows appear here and they are **different concepts** that happen to be about time:

- `CANDIDATE_IDLE_MINUTES` (imported from correlation, not redefined) decides whether a
  candidate is still open to new reports. It is the correlation baseline's own rule,
  already evaluated in M5/M6, and duplicating it with a different number here would give
  live intake different semantics from the thing that was measured.

- `REPLAY_WINDOW` decides how much history is fed back through the engine so existing
  groupings are reconstructed before the new ticket is offered to them. Wider than the
  idle window on purpose: reconstructing a candidate requires its members, which are older
  than the gap that keeps it open.

Neither is the investigation evidence window from M14. That one governs what an
investigator is shown; these govern what correlation considers. Related, not the same.
"""

from datetime import timedelta

from app.correlation.rules import CANDIDATE_IDLE_MINUTES

INTAKE_VERSION = "intake-v1"

# Live intake runs the **deterministic** baseline.
#
# It is the product default the UI already uses; M6 measured the semantic version as
# exactly zero delta on the authored set; and semantic correlation would add an embedding
# call — latency and a failure mode — to every ticket submission for no measured gain.
# Semantic remains available for batch comparison and is selectable by name.
LIVE_CORRELATION_MODE = "deterministic"

# Enough history to rebuild the candidates a new ticket might join. Four times the idle
# window: a candidate open for another 90 minutes may have started well before that.
REPLAY_WINDOW = timedelta(minutes=CANDIDATE_IDLE_MINUTES * 4)

# A ticket must beat the runner-up by this much for the choice to be called unambiguous.
# Below it the intake records `ambiguous` and attaches to nothing — inventing certainty
# between two plausible groupings is worse than saying it is unclear.
CANDIDATE_MARGIN = 0.05

# How far ahead of now a reported time may be. Clock skew between a reporter's machine and
# ours is minutes; anything beyond that is a typo or a bad integration, and accepting it
# would let a single ticket sit permanently in the future of every correlation window.
FUTURE_TOLERANCE = timedelta(minutes=5)

# Ticket text bounds. Generous: error codes, stack fragments and pasted logs are exactly
# the technical detail that makes a report useful, and truncating them would be
# destroying evidence to satisfy a schema.
MAX_TITLE = 300
MAX_DESCRIPTION = 8000
MAX_EXTERNAL_ID = 128

# Sources a caller may not claim. Provenance is server-owned: an API submission cannot
# present itself as an authored Northstar fixture.
RESERVED_SOURCES = frozenset({"northstar-authored", "imported", "external-eval"})
