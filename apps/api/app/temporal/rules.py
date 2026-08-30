"""Temporal windows and thresholds, in one place.

Three separate window constants existed before this module — `DEPLOYMENT_LOOKBACK` and
`SIGNAL_WINDOW` in the evidence tools, `DEPLOYMENT_BLAST_WINDOW` in the action policy —
each answering a slightly different question with no shared definition. They are gathered
here so "how far back do we look" has one answer that can be argued with.

**These are Northstar numbers, not production defaults.** The synthetic environment has
incidents that unfold over minutes and deployments that ship a few times a day. A real
estate would want windows that vary by service and by change type; picking one transparent
default is the honest thing to do at this scale, and pretending otherwise would be worse.
"""

from datetime import timedelta

# Bumped whenever a change here would alter how an old run should be read. Persisted on
# every InvestigationRun, so a stored investigation can be interpreted with the windows it
# was actually produced under rather than whatever the code says today.
TEMPORAL_CONFIG_VERSION = "temporal-window-v1"

# How far before symptom onset an event is still worth collecting. An hour covers the
# Northstar deployment-then-failure scenarios with room to spare, without dragging in the
# previous day's unrelated releases.
LOOKBACK = timedelta(minutes=60)

# How far after onset. Health recovering, errors continuing, later reports arriving: all
# of it describes the same incident and belongs in the window.
LOOKFORWARD = timedelta(minutes=30)

# How soon after a deployment a failure can still plausibly be attributed to it. Shorter
# than LOOKBACK on purpose: a deployment 55 minutes before the first symptom is worth
# *showing* an investigator, but calling it temporally plausible would stretch the word.
ATTRIBUTION_WINDOW = timedelta(minutes=30)

# Clocks are not perfectly synchronised and observation intervals are coarse. An event
# "after" another by less than this is treated as simultaneous rather than ordered, so a
# 20-second gap is never reported as a causal sequence.
SIMULTANEITY_TOLERANCE = timedelta(seconds=60)

# Health statuses that count as a symptom. `recovering` deliberately does not: a service
# on its way back up is not the start of an incident.
UNHEALTHY_STATUSES = frozenset({"degraded", "critical"})
SYMPTOM_STATUSES = UNHEALTHY_STATUSES
