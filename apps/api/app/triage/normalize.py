"""Text normalization.

Kept small and boring on purpose: every transformation is reversible in the reader's
head, so a rule author can predict what a phrase will match.
"""

import re
import unicodedata
from functools import lru_cache

# Expanded before punctuation is stripped, so "can't" and "cannot" match one phrase
# rather than needing two entries in every vocabulary.
CONTRACTIONS = {
    "cant": "cannot",
    "wont": "will not",
    "isnt": "is not",
    "arent": "are not",
    "doesnt": "does not",
    "didnt": "did not",
    "wasnt": "was not",
    "werent": "were not",
    "hasnt": "has not",
    "havent": "have not",
    "couldnt": "could not",
    "wouldnt": "would not",
    "im": "i am",
    "ive": "i have",
    "its": "it is",
    "theyre": "they are",
    "weve": "we have",
}

_NON_WORD = re.compile(r"[^a-z0-9]+")
_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercases, folds punctuation to spaces, and expands common contractions.

    The result is a single-spaced string of words, which makes phrase matching a plain
    substring search with word boundaries.
    """
    folded = unicodedata.normalize("NFKD", text or "").lower()
    # Apostrophes disappear rather than becoming spaces, so "can't" -> "cant" and the
    # contraction table can do its job.
    folded = folded.replace("'", "").replace("’", "")
    folded = _NON_WORD.sub(" ", folded)
    folded = _WHITESPACE.sub(" ", folded).strip()

    if not folded:
        return ""

    words = [CONTRACTIONS.get(word, word) for word in folded.split(" ")]
    return " ".join(words)


@lru_cache(maxsize=1024)
def _pattern(phrase: str) -> re.Pattern[str]:
    """Compiled once per phrase; the rule tables are fixed, so the cache is bounded.

    A trailing "s" is optional, so "export" matches "exports" and "dashboard" matches
    "dashboards" without every vocabulary carrying both. This is the whole of our
    stemming: crude, but predictable enough that a rule author can hold it in their head.
    """
    return re.compile(rf"(?<!\w){re.escape(phrase)}s?(?!\w)")


def contains_phrase(normalized_text: str, phrase: str) -> bool:
    """Whole-word phrase match against already-normalized text."""
    if not normalized_text or not phrase:
        return False
    return _pattern(phrase).search(normalized_text) is not None
