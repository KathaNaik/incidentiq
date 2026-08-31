"""Correlation weights and thresholds — every tunable number in one file.

The scoring shape:

    content  = w_service·service + w_issue·issue + w_lexical·lexical + w_entity·entity
    pair     = W_TIME·time + (1 - W_TIME)·content

Component scores run from -1 (argues against) through 0 (says nothing) to +1 (argues
for), so a conflict subtracts rather than merely failing to add.

Attachment to an existing candidate applies the two halves differently, which is the
main safeguard against chaining:

- **content** must clear `CONTENT_LINK_MIN` against *every* member (complete linkage).
  A ticket joins a group only if it resembles all of it, so A–B–C cannot form when A
  and C are unrelated.
- **time** is measured against the *nearest* member, not the oldest. A four-day outage
  keeps accumulating tickets; requiring proximity to the first report would make long
  incidents impossible to correlate.

Values were set on the authored golden set (`data/evals/correlation/`), never against
the external benchmark.
"""

from app.triage.models import IssueType

CORRELATION_VERSION = "deterministic-correlation-v1"
SEMANTIC_CORRELATION_VERSION = "semantic-correlation-v1"

# v2 changes no weight and no threshold. It changes *reconciliation*: which durable
# candidate a recomputed cluster belongs to is still decided by membership overlap, but
# an arriving ticket now has to earn its membership against that candidate rather than
# inherit it. See `reconcile.py` for the rule and the defect it closes.
CORRELATION_VERSION_V2 = "deterministic-correlation-v2"

# --- component weights (content weights sum to 1.0) -------------------------------
W_TIME = 0.35
W_SERVICE = 0.40
W_ISSUE = 0.15
W_LEXICAL = 0.25
W_ENTITY = 0.20

# With semantic similarity available, weight moves off lexical overlap and service —
# but lexical keeps real influence, because exact term overlap (an error code quoted in
# prose, a product noun) is evidence the embedding blurs together. Identifiers keep
# their full weight: they were the strongest non-temporal evidence in the deterministic
# baseline and nothing about embeddings changes that. Sums to 1.0, like the
# deterministic set.
#
# Five weightings spanning lexical-heavy to semantic-heavy scored *identically* on the
# authored golden set — 26 tickets cannot separate them — so this one is chosen on the
# reasoning above rather than by fitting. Polaris was not consulted.
W_SERVICE_SEMANTIC = 0.32
W_ISSUE_SEMANTIC = 0.12
W_LEXICAL_SEMANTIC = 0.18
W_ENTITY_SEMANTIC = 0.18
W_SEMANTIC = 0.20

# Raw cosine is rescaled onto [0, 1] between these bounds. This model scores two
# unrelated support tickets around 0.6, so without a floor every pair would receive a
# large constant bonus. Set on the authored golden set; see the milestone report for the
# distribution that motivated them.
SEMANTIC_FLOOR = 0.72
SEMANTIC_CEILING = 0.90

# --- time decay --------------------------------------------------------------------
# Half-life in minutes: 0 min -> 1.00, 20 -> 0.50, 40 -> 0.25, 60 -> 0.13, 120 -> 0.02.
# An ops team triaging a live incident treats reports inside the hour as adjacent;
# past that, a new report is more likely a different problem than a late duplicate.
TIME_HALF_LIFE_MINUTES = 20.0

# --- thresholds --------------------------------------------------------------------
# Overall bar for linking a ticket into a candidate.
LINK_THRESHOLD = 0.60
# Complete-linkage bar: content similarity against the weakest member.
CONTENT_LINK_MIN = 0.50
# Nearest-member time score floor (~0.12 is a little over an hour).
TIME_LINK_MIN = 0.12
# A candidate stops accepting tickets once it has been quiet this long.
CANDIDATE_IDLE_MINUTES = 90.0
# Post-hoc cohesion check: a formed group whose mean pairwise score falls below this is
# dissolved back into standalone tickets. Complete linkage makes this rare; it exists so
# a weak group cannot survive a future change to the attachment rule.
COHESION_MIN = 0.55

# Precision is worth more than recall here: a false merge invents a major incident that
# is not happening and sends people chasing it, while a missed correlation leaves a
# ticket where it already was. Every threshold above is set on the strict side, and the
# evaluation reports false-merge rate alongside recall so the trade stays visible.

# --- confidence bands ---------------------------------------------------------------
CONFIDENCE_HIGH = 0.75
CONFIDENCE_MEDIUM = 0.65

# --- lexical ------------------------------------------------------------------------
# Ordinary English filler plus support-desk boilerplate. Product vocabulary is *not*
# listed here — it is handled by inverse document frequency, which learns from the
# tickets at hand that "dashboard" is uninformative in a corpus full of dashboards.
STOP_WORDS = frozenset(
    """
    a an the and or but if then than so because of to in on at for with without from by
    is are was were be been being am do does did doing have has had having i we you they
    it he she this that these those there here as into over under out up down about
    can cannot could should would will not no nor also very just only same other some any
    please thanks thank hi hello hey team support ticket issue problem help need
    when what which who whom how why our your their my me us them
    """.split()
)
# Below this, a token is noise ("a", "is"); at or above, it can carry meaning.
MIN_TOKEN_LENGTH = 3

# --- issue-type compatibility --------------------------------------------------------
# Deliberately tiny. Anything not listed is neither compatible nor contradictory, and
# scores 0 — the pair is judged on its other evidence.
COMPATIBLE_ISSUE_TYPES: frozenset[frozenset[str]] = frozenset(
    {
        # A degrading service produces both "it's down" and "it's crawling".
        frozenset({IssueType.AVAILABILITY.value, IssueType.PERFORMANCE.value}),
        # A broken sync shows up as an outage to one reporter and as stale numbers
        # to the next.
        frozenset({IssueType.AVAILABILITY.value, IssueType.DATA_QUALITY.value}),
        frozenset({IssueType.INTEGRATION.value, IssueType.AVAILABILITY.value}),
        frozenset({IssueType.CONFIGURATION.value, IssueType.INTEGRATION.value}),
    }
)
CONTRADICTORY_ISSUE_TYPES: frozenset[frozenset[str]] = frozenset(
    {
        # "I am denied access" and "the service is down for everyone" are different
        # problems that happen to look alike in a ticket queue.
        frozenset({IssueType.PERMISSIONS.value, IssueType.AVAILABILITY.value}),
        frozenset({IssueType.PERMISSIONS.value, IssueType.PERFORMANCE.value}),
    }
)

SAME_ISSUE_SCORE = 1.0
COMPATIBLE_ISSUE_SCORE = 0.5
CONTRADICTORY_ISSUE_SCORE = -1.0

SAME_SERVICE_SCORE = 1.0
DIFFERENT_SERVICE_SCORE = -1.0
# One side unknown is not evidence against grouping — it is an absence of evidence.
UNKNOWN_SERVICE_SCORE = 0.0

# --- entities ------------------------------------------------------------------------
# A shared error code or identifier is the strongest non-temporal evidence there is:
# two people rarely quote "ERR_AUTH_17" by coincidence.
SHARED_IDENTIFIER_SCORE = 1.0
# Shared symptom vocabulary (both say "stale data") is weaker but real.
SHARED_SYMPTOM_SCORE = 0.5


# --- hybrid correlation (M16) ----------------------------------------------------------
#
# A third strategy, not a change to either baseline above. Deterministic scoring decides
# almost everything; semantic evidence is computed only when the deterministic pass says a
# candidate is operationally plausible AND that lexical overlap was the failing signal.
HYBRID_CORRELATION_VERSION = "hybrid-correlation-v1"

# The fallback policy is versioned separately from the strategy, because the conditions
# under which an embedding is worth computing may change without the strategy changing.
FALLBACK_POLICY_VERSION = "fallback-policy-v1"

# Lexical component score at or below which lexical is treated as the limiting signal.
# Not a score band on the blended total: a band would also fire for tickets sitting near
# the threshold for entirely different reasons, and those are not paraphrases. Set where
# the lexical signal has clearly stopped carrying evidence rather than merely being
# modest — a genuine wording match on this corpus scores well above it.
LEXICAL_WEAKNESS_MAX = 0.35

# --- pairwise correlation (M18) ---------------------------------------------------------
#
# A fourth strategy. Same M16 gate, same hard conflicts, same cohesion — the only change is
# what scores the ambiguous slice: a supervised classifier over structured signals instead
# of embedding cosine.
PAIRWISE_CORRELATION_VERSION = "pairwise-correlation-v1"
