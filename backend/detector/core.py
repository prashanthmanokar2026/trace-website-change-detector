"""Pure comparison rules. Browser fetching and notification delivery are separate.

No broad number/token stripping: prices, dates and identifiers can be meaningful.
"""
from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256
import re
import unicodedata
from typing import Optional


@dataclass(frozen=True)
class Comparison:
    content_hash: str
    new_version: bool
    meaningful: bool
    changed_fraction: float


def normalize(text: str) -> str:
    """Normalize Unicode and line whitespace while preserving words and numbers."""
    text = unicodedata.normalize("NFC", text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def content_hash(text: str) -> str:
    return sha256(normalize(text).encode("utf-8")).hexdigest()


def compare(previous: Optional[str], current: str, *,
            significant_baseline: Optional[str] = None,
            threshold: float = 0.0) -> Comparison:
    """Keep versions independently of the threshold used for alert significance.

    Threshold is a changed-token fraction in [0, 1]. A caller should pass the last
    significant baseline to detect accumulated small edits. Initial capture is
    a baseline and never a meaningful change. Input sizes must be bounded by the
    extraction layer; this function is not a hostile-input resource boundary.
    """
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    normalized = normalize(current)
    digest = content_hash(normalized)
    if previous is None:
        return Comparison(digest, True, False, 0.0)
    changed = content_hash(previous) != digest
    reference = previous if significant_baseline is None else significant_baseline
    old = re.findall(r"\w+|[^\w\s]", normalize(reference))
    new = re.findall(r"\w+|[^\w\s]", normalized)
    fraction = 1.0 - SequenceMatcher(None, old, new, autojunk=False).ratio()
    meaningful = changed and fraction > 0 and fraction >= threshold
    return Comparison(digest, changed, meaningful, fraction)
