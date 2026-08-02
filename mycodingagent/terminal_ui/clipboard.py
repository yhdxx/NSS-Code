from __future__ import annotations

import base64
import sys
from typing import TextIO


_INTERNAL_CLIPBOARD = ""
MAX_OSC52_BYTES = 100_000


def copy_to_clipboard(text: str, *, file: TextIO | None = None) -> bool:
    """Copy text through OSC52 when possible and always keep an internal fallback."""
    global _INTERNAL_CLIPBOARD
    _INTERNAL_CLIPBOARD = text
    output = file or sys.stdout
    if not text or not hasattr(output, "isatty") or not output.isatty():
        return False
    encoded = base64.b64encode(text.encode("utf-8"))
    if len(encoded) > MAX_OSC52_BYTES:
        return False
    try:
        output.write("\033]52;c;" + encoded.decode("ascii") + "\a")
        output.flush()
    except Exception:
        return False
    return True


def paste_from_clipboard() -> str:
    return _INTERNAL_CLIPBOARD


def clear_internal_clipboard() -> None:
    global _INTERNAL_CLIPBOARD
    _INTERNAL_CLIPBOARD = ""
