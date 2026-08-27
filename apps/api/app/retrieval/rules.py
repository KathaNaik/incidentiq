"""Retrieval weights and thresholds, in one place.

Ranking:

    score = W_SIMILARITY·cosine + W_SERVICE·service_overlap + W_ERROR·error_overlap

The reranking terms are small on purpose. Semantic similarity does the retrieving; a
shared service or a shared error code breaks ties between candidates that already look
alike. Letting them dominate would rank every ticket mentioning the same application
above a genuinely matching failure pattern — the exact failure the deterministic
correlation baseline showed.
"""

RETRIEVAL_VERSION = "historical-retrieval-v1"

W_SIMILARITY = 0.80
W_SERVICE = 0.08
W_ERROR = 0.12

DEFAULT_K = 5
MAX_K = 25

# Below this score, the top hit is not precedent — it is the least-bad row in the
# corpus. Set from the measured separation on the external corpus: pairs describing the
# same failure score 0.78 and up, pairs from different failures rarely pass 0.70. A
# result under the threshold is returned but marked, so the UI can say "nothing
# convincing" instead of presenting five confident-looking rows.
STRONG_MATCH_SCORE = 0.75

# Service names arrive from two vocabularies — Northstar service ids and the external
# corpus's free-text application names — so matching is done on normalized tokens rather
# than exact strings.
SERVICE_STOP_WORDS = frozenset({"service", "services", "portal", "app", "application"})
