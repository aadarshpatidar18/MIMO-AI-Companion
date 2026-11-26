"""Deterministic pre-checks that run before the LLM intent classifier."""
import re

_NOUNS = {
    "interest": r"interests?|hobbies|hobby",
    "skill": r"skills?",
    "goal": r"goals?|ambitions?",
    "project": r"projects?",
    "preference": r"preferences?",
    "education": r"education|studies",
}

# "what are my ...", "list my ...", "do you remember (about) my ..."
_PREFIX = (
    r"(?:(?:what|which)\s+(?:are|is|were)"
    r"|(?:list|show|tell\s+me)(?:\s+me)?(?:\s+all)?(?:\s+of)?"
    r"|(?:what\s+)?do\s+you\s+(?:remember|know)(?:\s+about)?)"
)

_PATTERNS = [
    (category, re.compile(rf"^\s*{_PREFIX}\s+my\s+(?:\w+\s+)?(?:{nouns})\b", re.IGNORECASE))
    for category, nouns in _NOUNS.items()
]


def detect_memory_category(message):
    """Return a memory category only for explicit recall questions.

    The previous rule matched any sentence containing "my " plus a keyword such
    as "project" or "learn", so "Help me debug my project" was answered with a
    memory dump. Ambiguous phrasings now fall through to the intent classifier.
    """
    for category, pattern in _PATTERNS:
        if pattern.search(message):
            return category
    return None
