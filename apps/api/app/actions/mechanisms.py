"""What kind of failure an error signature represents.

Policy needs to answer a question the evidence does not state outright: *does restarting
the service address the mechanism that is failing?* A stalled worker and an invalid SAML
certificate both make a service degraded, and only one of them is fixed by a restart.

This is a closed lookup table from error code to mechanism, owned by the application.
Three properties matter:

**It reads codes, not prose.** Error codes are a small controlled vocabulary emitted by
services. The sample messages beside them are free text and are deliberately not consulted
— policy that greps English is policy that a reworded log line can flip.

**It is not in the prompt.** Nothing here reaches the model, so a mechanism label cannot
leak the expected action into an evaluation case. The model reasons from the same evidence
it always did; the categorisation happens afterwards, on our side of the boundary.

**An unknown code is not a transient failure.** `UNKNOWN` is the default and it does not
satisfy the restart-relevance check. A new error code makes restarts *harder* to approve
until somebody classifies it, which is the correct direction to fail.
"""

from enum import StrEnum


class FailureMechanism(StrEnum):
    """The kind of thing that is broken, as distinct from the fact that something is."""

    TRANSIENT_RUNTIME = "transient_runtime"
    """Process or worker state: stalls, missed heartbeats, leaks, wedged instances.

    The one mechanism a restart actually addresses — it discards the bad in-process state
    and starts clean.
    """

    CONFIGURATION = "configuration"
    """Wrong or mismatched configuration. Survives a restart, because it is reloaded."""

    AUTHENTICATION = "authentication"
    """Credentials, tokens, certificates, trust. A restart re-reads the same bad secret."""

    PERMISSIONS = "permissions"
    """Authorisation denied. Restarting changes nothing about what the caller may do."""

    DATA_QUALITY = "data_quality"
    """The data is wrong or truncated. The process is doing what it was told."""

    EXTERNAL_DEPENDENCY = "external_dependency"
    """Something downstream is failing. Restarting ours just reconnects to a broken thing."""

    UNKNOWN = "unknown"
    """Unclassified. Deliberately not restart-relevant."""


# The mechanism a restart is designed to clear. Kept as a set rather than an equality
# check so that adding another restart-addressable mechanism is a one-line change here
# instead of an edit inside the policy logic.
RESTART_ADDRESSABLE = frozenset({FailureMechanism.TRANSIENT_RUNTIME})

# Mechanisms that actively argue against a restart: the failure is somewhere a restart
# cannot reach, so bouncing the service costs an outage and fixes nothing.
RESTART_CONTRAINDICATED = frozenset(
    {
        FailureMechanism.CONFIGURATION,
        FailureMechanism.AUTHENTICATION,
        FailureMechanism.PERMISSIONS,
        FailureMechanism.DATA_QUALITY,
        FailureMechanism.EXTERNAL_DEPENDENCY,
    }
)

# Northstar's error vocabulary. Small on purpose: these are the codes our own synthetic
# services emit, and every one of them was classified by hand.
ERROR_MECHANISMS: dict[str, FailureMechanism] = {
    # Connector: the worker is alive but wedged — exactly what a restart clears.
    "ERR_SYNC_STALLED": FailureMechanism.TRANSIENT_RUNTIME,
    "ERR_WORKER_OOM": FailureMechanism.TRANSIENT_RUNTIME,
    # Auth: a certificate the config does not trust. Restarting reloads the same config.
    "ERR_SAML_INVALID_ASSERTION": FailureMechanism.CONFIGURATION,
    "401": FailureMechanism.AUTHENTICATION,
    "ERR_TOKEN_EXPIRED": FailureMechanism.AUTHENTICATION,
    "403": FailureMechanism.PERMISSIONS,
    # Analytics: the export ran correctly and produced wrong output.
    "ERR_EXPORT_TRUNCATED": FailureMechanism.DATA_QUALITY,
    # Downstream.
    "ERR_UPSTREAM_TIMEOUT": FailureMechanism.EXTERNAL_DEPENDENCY,
    "502": FailureMechanism.EXTERNAL_DEPENDENCY,
}


def mechanism_of(error_code: str) -> FailureMechanism:
    """Classifies one error code. Unknown codes are UNKNOWN, never guessed."""
    return ERROR_MECHANISMS.get(error_code, FailureMechanism.UNKNOWN)
