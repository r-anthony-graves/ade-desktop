"""The wake word -- the avatar's rule, verbatim (adeos/avatar/ui.js WAKE).

"Ade", "Hey Ade", "Ada" and "Aday" all transcribe to one token on the live
recogniser (measured by the avatar, 2026-08-27). A separator and more text
are required, so "Adelaide" never wakes it.
"""

from __future__ import annotations

import re

WAKE = re.compile(r"^\s*(?:hey\s+|ok\s+)?ad[ae]y?\s*[,.!?:-]?\s+", re.I)


def strip_wake(text) -> str | None:
    """The command after the wake word, or None if it was not woken."""
    if text is None:
        return None
    m = WAKE.match(str(text))
    return str(text)[m.end():].strip() if m else None
