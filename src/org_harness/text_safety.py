"""Validate text at producer boundaries without changing its meaning or bytes."""

import re
from collections.abc import Mapping
from typing import Any

_INVALID_TEXT = re.compile("[\x00\ud800-\udfff]")


def contains_invalid_json_text(value: Any) -> bool:
    """Detect PostgreSQL-incompatible NUL and non-scalar Unicode recursively.

    Literal backslash escape sequences are ordinary text. JSON-decoded valid
    surrogate pairs become Unicode scalar characters and remain supported.
    """
    pending = [value]
    visited: set[int] = set()
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if _INVALID_TEXT.search(item):
                return True
        elif isinstance(item, Mapping):
            if id(item) not in visited:
                visited.add(id(item))
                pending.extend(item.keys())
                pending.extend(item.values())
        elif isinstance(item, (list, tuple, set, frozenset)) and id(item) not in visited:
            visited.add(id(item))
            pending.extend(item)
    return False


def require_json_text[ValueT](value: ValueT) -> ValueT:
    """Reject invalid text; do not silently sanitize requests or fingerprints."""
    if contains_invalid_json_text(value):
        raise ValueError("Text contains U+0000 or an unsupported Unicode surrogate")
    return value
