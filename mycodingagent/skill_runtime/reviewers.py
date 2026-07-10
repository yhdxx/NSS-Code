from __future__ import annotations

from pathlib import Path

from mycodingagent.skill_runtime.models import ReviewResult


async def review_skill_code(source_path: Path, content: str) -> ReviewResult:
    """Entry point for future malicious-code review.

    The real implementation should inspect files, scripts, and executable
    snippets referenced by a skill. For now it approves by default so the
    runtime wiring can be developed and tested.
    """
    return ReviewResult(approved=True)


async def review_skill_prompt(source_path: Path, content: str) -> ReviewResult:
    """Entry point for future prompt-injection and instruction-risk review."""
    return ReviewResult(approved=True)
