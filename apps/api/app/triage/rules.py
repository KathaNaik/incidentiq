"""Triage rules, as data.

Everything here is a table an engineer can read and edit without touching the scoring
code. Weights follow one convention:

- **3.0 — decisive.** The phrase means one thing in this product ("cannot log in", "sso").
- **2.0 — indicative.** Usually right, occasionally shared ("password", "export").
- **1.0 — weak.** Common vocabulary that only matters when nothing stronger fires ("api").

Service ids match the Northstar Cloud fixtures; a test asserts they still exist.
"""

from dataclasses import dataclass

from app.triage.models import IssueType, SignalType, TicketPriority

TRIAGE_VERSION = "deterministic-v1"

# A title states the problem; a body often wanders. Matches in the title count for more.
TITLE_WEIGHT_MULTIPLIER = 1.5

# A winner must beat the runner-up by this much, or the prediction is ambiguous.
AMBIGUITY_MARGIN = 1.5


@dataclass(frozen=True)
class Phrase:
    text: str
    weight: float
    # Canonical meaning, so "everyone" and "all users" explain as one thing.
    value: str = ""

    @property
    def normalized_value(self) -> str:
        return self.value or self.text


@dataclass(frozen=True)
class ServiceRule:
    service_id: str
    display_name: str
    phrases: tuple[Phrase, ...]


@dataclass(frozen=True)
class IssueRule:
    issue_type: IssueType
    phrases: tuple[Phrase, ...]


@dataclass(frozen=True)
class PriorityRule:
    signal_type: SignalType
    # Positive raises priority, negative lowers it.
    phrases: tuple[Phrase, ...]


SERVICE_RULES: tuple[ServiceRule, ...] = (
    ServiceRule(
        service_id="svc-auth",
        display_name="Authentication",
        phrases=(
            Phrase("cannot log in", 3.0, "login_failure"),
            Phrase("cannot sign in", 3.0, "login_failure"),
            Phrase("unable to log in", 3.0, "login_failure"),
            Phrase("unable to sign in", 3.0, "login_failure"),
            Phrase("login loop", 3.0, "login_failure"),
            Phrase("sso", 3.0, "sso"),
            Phrase("single sign on", 3.0, "sso"),
            Phrase("saml", 3.0, "sso"),
            Phrase("oidc", 3.0, "sso"),
            Phrase("identity provider", 3.0, "sso"),
            Phrase("invalid assertion", 3.0, "sso"),
            Phrase("okta", 3.0, "sso"),
            Phrase("mfa", 3.0, "mfa"),
            Phrase("two factor", 3.0, "mfa"),
            Phrase("password reset", 3.0, "password"),
            Phrase("account locked", 3.0, "account_lockout"),
            Phrase("api token", 3.0, "token"),
            Phrase("access token", 3.0, "token"),
            Phrase("logging me out", 2.0, "session"),
            Phrase("logs me out", 2.0, "session"),
            Phrase("log in", 2.0, "login"),
            Phrase("login", 2.0, "login"),
            Phrase("sign in", 2.0, "login"),
            Phrase("signin", 2.0, "login"),
            Phrase("logged out", 2.0, "session"),
            Phrase("authentication", 2.0, "authentication"),
            Phrase("authenticate", 2.0, "authentication"),
            Phrase("credentials", 2.0, "credentials"),
            Phrase("password", 2.0, "password"),
            Phrase("unauthorized", 2.0, "unauthorized"),
            Phrase("401", 2.0, "unauthorized"),
            Phrase("session", 1.0, "session"),
            Phrase("token", 1.0, "token"),
        ),
    ),
    ServiceRule(
        service_id="svc-analytics",
        display_name="Analytics Dashboard",
        phrases=(
            Phrase("dashboard", 3.0, "dashboard"),
            Phrase("saved report", 3.0, "report"),
            Phrase("analytics", 3.0, "analytics"),
            Phrase("widget", 3.0, "dashboard"),
            Phrase("visualization", 3.0, "chart"),
            Phrase("chart", 2.0, "chart"),
            Phrase("graph", 2.0, "chart"),
            Phrase("report", 2.0, "report"),
            Phrase("kpi", 2.0, "metrics"),
            Phrase("metrics", 2.0, "metrics"),
            Phrase("csv export", 2.0, "export"),
            Phrase("export", 1.0, "export"),
            Phrase("tile", 1.0, "dashboard"),
        ),
    ),
    ServiceRule(
        service_id="svc-connector",
        display_name="Connector API",
        phrases=(
            Phrase("connector", 3.0, "connector"),
            Phrase("sync", 3.0, "sync"),
            Phrase("syncing", 3.0, "sync"),
            Phrase("resync", 3.0, "sync"),
            Phrase("webhook", 3.0, "webhook"),
            Phrase("warehouse", 3.0, "warehouse"),
            Phrase("snowflake", 3.0, "warehouse"),
            Phrase("bigquery", 3.0, "warehouse"),
            Phrase("redshift", 3.0, "warehouse"),
            Phrase("pipeline", 2.0, "pipeline"),
            Phrase("ingest", 2.0, "pipeline"),
            Phrase("endpoint", 2.0, "api"),
            Phrase("504", 2.0, "gateway"),
            Phrase("502", 2.0, "gateway"),
            Phrase("api", 1.0, "api"),
        ),
    ),
)

ISSUE_RULES: tuple[IssueRule, ...] = (
    IssueRule(
        IssueType.AVAILABILITY,
        (
            Phrase("outage", 3.0, "outage"),
            Phrase("is down", 3.0, "down"),
            Phrase("are down", 3.0, "down"),
            Phrase("completely down", 3.0, "down"),
            Phrase("unavailable", 3.0, "unavailable"),
            Phrase("cannot access", 3.0, "cannot_access"),
            Phrase("stopped working", 3.0, "stopped_working"),
            Phrase("not working at all", 3.0, "stopped_working"),
            Phrase("cannot load", 3.0, "cannot_load"),
            Phrase("will not load", 3.0, "cannot_load"),
            Phrase("does not load", 3.0, "cannot_load"),
            Phrase("stops working", 3.0, "stopped_working"),
            Phrase("no longer works", 3.0, "stopped_working"),
            Phrase("stopped loading", 3.0, "cannot_load"),
            Phrase("not loading", 3.0, "cannot_load"),
            Phrase("never renders", 3.0, "cannot_load"),
            Phrase("will not render", 3.0, "cannot_load"),
            Phrase("stuck", 2.0, "stuck"),
            Phrase("gateway timeout", 3.0, "timeout"),
            Phrase("503", 3.0, "server_error"),
            Phrase("504", 2.0, "server_error"),
            Phrase("502", 2.0, "server_error"),
            Phrase("500", 2.0, "server_error"),
            Phrase("times out", 2.0, "timeout"),
            Phrase("failing", 2.0, "failing"),
            Phrase("broken", 2.0, "broken"),
            Phrase("crash", 2.0, "crash"),
        ),
    ),
    IssueRule(
        IssueType.PERFORMANCE,
        (
            Phrase("slow", 3.0, "slow"),
            Phrase("slowly", 3.0, "slow"),
            Phrase("sluggish", 3.0, "slow"),
            Phrase("takes forever", 3.0, "slow"),
            Phrase("latency", 3.0, "latency"),
            Phrase("spinning", 3.0, "spinning"),
            Phrase("timing out after", 2.0, "timeout"),
            Phrase("lag", 2.0, "latency"),
            Phrase("laggy", 2.0, "latency"),
            Phrase("performance", 2.0, "performance"),
            Phrase("takes several seconds", 2.0, "slow"),
            Phrase("delay", 1.0, "delay"),
        ),
    ),
    IssueRule(
        IssueType.DATA_QUALITY,
        (
            Phrase("numbers are wrong", 3.0, "wrong_values"),
            Phrase("incorrect data", 3.0, "wrong_values"),
            Phrase("wrong values", 3.0, "wrong_values"),
            Phrase("does not match", 3.0, "mismatch"),
            Phrase("do not match", 3.0, "mismatch"),
            Phrase("mismatch", 3.0, "mismatch"),
            Phrase("out of date", 3.0, "stale"),
            Phrase("day behind", 3.0, "stale"),
            Phrase("stale", 3.0, "stale"),
            Phrase("duplicate rows", 3.0, "duplicates"),
            Phrase("missing rows", 3.0, "missing_data"),
            Phrase("missing data", 3.0, "missing_data"),
            Phrase("truncated", 3.0, "truncated"),
            Phrase("stops at", 2.0, "truncated"),
            Phrase("inaccurate", 2.0, "wrong_values"),
            Phrase("double counted", 2.0, "duplicates"),
        ),
    ),
    IssueRule(
        IssueType.CONFIGURATION,
        (
            Phrase("misconfigured", 3.0, "misconfiguration"),
            Phrase("configuration", 3.0, "configuration"),
            Phrase("configure", 3.0, "configuration"),
            Phrase("set up", 2.0, "setup"),
            Phrase("setup", 2.0, "setup"),
            Phrase("settings", 2.0, "settings"),
            Phrase("setting", 1.0, "settings"),
            Phrase("wrong region", 2.0, "misconfiguration"),
            Phrase("default value", 1.0, "settings"),
        ),
    ),
    IssueRule(
        IssueType.PERMISSIONS,
        (
            Phrase("permission denied", 3.0, "denied"),
            Phrase("access denied", 3.0, "denied"),
            Phrase("not authorized", 3.0, "denied"),
            Phrase("forbidden", 3.0, "denied"),
            Phrase("403", 3.0, "denied"),
            Phrase("permissions", 3.0, "permissions"),
            Phrase("permission", 2.0, "permissions"),
            Phrase("admin rights", 3.0, "role"),
            Phrase("read only", 2.0, "role"),
            Phrase("greyed out", 2.0, "denied"),
            Phrase("grayed out", 2.0, "denied"),
            Phrase("role", 2.0, "role"),
            Phrase("cannot see", 2.0, "visibility"),
            Phrase("no longer see", 2.0, "visibility"),
            Phrase("grant access", 2.0, "access_request"),
        ),
    ),
    IssueRule(
        # Deliberately about the *handoff between systems*, not about the connector
        # service. "third party", "callback" and an expiring external credential are
        # integration problems whichever service they land in.
        IssueType.INTEGRATION,
        (
            Phrase("third party", 3.0, "third_party"),
            Phrase("external system", 3.0, "third_party"),
            Phrase("callback", 3.0, "callback"),
            Phrase("redirect", 2.0, "callback"),
            Phrase("oauth app", 3.0, "oauth"),
            Phrase("api key expired", 3.0, "expired_credential"),
            Phrase("certificate expired", 3.0, "expired_credential"),
            Phrase("certificate", 2.0, "certificate"),
            Phrase("rotation", 2.0, "credential_rotation"),
            Phrase("expiring", 2.0, "expired_credential"),
            Phrase("expired", 2.0, "expired_credential"),
            Phrase("provisioning", 2.0, "provisioning"),
            Phrase("group sync", 3.0, "provisioning"),
            Phrase("group membership", 2.0, "provisioning"),
            Phrase("upstream", 2.0, "upstream"),
            Phrase("handshake", 2.0, "handshake"),
        ),
    ),
)

PRIORITY_RULES: tuple[PriorityRule, ...] = (
    PriorityRule(
        # Scope is tiered: "everyone" is materially worse than "several people", so it
        # carries more weight rather than relying on more phrases happening to match.
        SignalType.SCOPE,
        (
            Phrase("all users", 4.0, "all_users"),
            Phrase("everyone", 4.0, "all_users"),
            Phrase("every user", 4.0, "all_users"),
            Phrase("nobody can", 4.0, "all_users"),
            Phrase("no one can", 4.0, "all_users"),
            Phrase("company wide", 4.0, "org_wide"),
            Phrase("all customers", 4.0, "all_customers"),
            Phrase("every customer", 4.0, "all_customers"),
            Phrase("entire team", 3.0, "team_wide"),
            Phrase("whole team", 3.0, "team_wide"),
            Phrase("multiple customers", 2.0, "multiple_users"),
            Phrase("multiple users", 2.0, "multiple_users"),
            Phrase("several users", 2.0, "multiple_users"),
        ),
    ),
    PriorityRule(
        SignalType.OUTAGE,
        (
            Phrase("outage", 3.0, "outage"),
            Phrase("is down", 3.0, "down"),
            Phrase("are down", 3.0, "down"),
            Phrase("completely down", 3.0, "down"),
            Phrase("unavailable", 3.0, "unavailable"),
            Phrase("cannot access", 3.0, "cannot_access"),
            Phrase("stopped working", 3.0, "stopped_working"),
            Phrase("not working at all", 3.0, "stopped_working"),
            Phrase("data loss", 3.0, "data_loss"),
        ),
    ),
    PriorityRule(
        SignalType.URGENCY,
        (
            Phrase("production", 2.0, "production"),
            Phrase("customer facing", 2.0, "customer_facing"),
            Phrase("blocked", 2.0, "blocked"),
            Phrase("blocking", 2.0, "blocked"),
            Phrase("urgent", 2.0, "urgent"),
            Phrase("asap", 2.0, "urgent"),
            Phrase("escalated", 2.0, "escalated"),
            Phrase("sla", 2.0, "sla"),
            Phrase("revenue", 2.0, "revenue"),
            Phrase("board meeting", 2.0, "deadline"),
            Phrase("deadline", 2.0, "deadline"),
        ),
    ),
    PriorityRule(
        SignalType.DEGRADATION,
        (
            Phrase("slow", 1.0, "slow"),
            Phrase("intermittent", 1.0, "intermittent"),
            Phrase("intermittently", 1.0, "intermittent"),
            Phrase("sometimes", 1.0, "intermittent"),
            Phrase("occasionally", 1.0, "intermittent"),
            Phrase("degraded", 1.0, "degraded"),
            Phrase("delayed", 1.0, "delayed"),
        ),
    ),
    PriorityRule(
        SignalType.LOCALIZED,
        (
            Phrase("my account", -2.0, "single_user"),
            Phrase("only me", -2.0, "single_user"),
            Phrase("just me", -2.0, "single_user"),
            Phrase("one user", -2.0, "single_user"),
            Phrase("single user", -2.0, "single_user"),
            Phrase("my laptop", -2.0, "single_machine"),
            Phrase("on my machine", -2.0, "single_machine"),
            Phrase("workaround exists", -2.0, "workaround"),
        ),
    ),
    PriorityRule(
        SignalType.INTENT,
        (
            Phrase("how do i", -2.0, "how_to"),
            Phrase("how can i", -2.0, "how_to"),
            Phrase("question about", -2.0, "how_to"),
            Phrase("where is that", -2.0, "how_to"),
            Phrase("is it possible", -2.0, "how_to"),
            Phrase("feature request", -2.0, "feature_request"),
            Phrase("would be nice", -2.0, "feature_request"),
            Phrase("nice to have", -2.0, "feature_request"),
            Phrase("no rush", -2.0, "no_rush"),
            Phrase("whenever you get a chance", -2.0, "no_rush"),
        ),
    ),
)

# Each dimension contributes its single strongest match, not the sum of every phrase
# that fired. Saying "the entire team" and "every user" in one ticket is one fact about
# scope stated twice; summing them would let verbose tickets outrank severe ones.
#
# Score bands. Explicit rather than derived so the whole policy is one table.
PRIORITY_BANDS: tuple[tuple[float, TicketPriority], ...] = (
    (6.0, TicketPriority.CRITICAL),
    (4.0, TicketPriority.HIGH),
    (2.0, TicketPriority.MEDIUM),
)
LOWEST_BAND = TicketPriority.LOW

# When no priority phrase matches at all, the ticket gets the neutral band rather than
# a guess in either direction. Burying it as low risks missing a terse outage; calling
# it high floods the queue. `status` records that this was a default, not a judgement.
NO_EVIDENCE_PRIORITY = TicketPriority.MEDIUM
