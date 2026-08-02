from __future__ import annotations

from .registry import (
    HIGHLIGHTERS,
    LanguageId,
    detect_language,
    highlight_for_terminal,
    language_from_path,
    language_from_shebang,
    looks_like_markdown,
    normalize_language,
)

__all__ = [
    "HIGHLIGHTERS",
    "LanguageId",
    "detect_language",
    "highlight_for_terminal",
    "language_from_path",
    "language_from_shebang",
    "looks_like_markdown",
    "normalize_language",
]
