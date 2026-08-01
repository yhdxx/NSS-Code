from __future__ import annotations

import re
from pathlib import Path


class AgentIgnore:
    """Match project-relative paths using common .gitignore-style rules."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve(strict=False)
        self.path = self.workspace_root / ".agentignore"
        self._rules: list[tuple[bool, bool, re.Pattern[str]]] = []
        self.reload()

    def reload(self) -> None:
        self._rules = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            if negated:
                line = line[1:].lstrip()
            directory_only = line.endswith("/")
            line = line.rstrip("/")
            anchored = line.startswith("/")
            line = line.lstrip("/")
            if line:
                self._rules.append((negated, directory_only, self._compile(line, anchored)))

    def is_ignored(self, relative_path: str, *, is_dir: bool = False) -> bool:
        relative = relative_path.replace("\\", "/").strip("/")
        if not relative:
            return False
        ignored = False
        parts = relative.split("/")
        candidates = ["/".join(parts[:index]) for index in range(1, len(parts) + 1)]
        for candidate in candidates:
            candidate_is_dir = candidate != relative or is_dir
            for negated, directory_only, pattern in self._rules:
                if directory_only and not candidate_is_dir:
                    continue
                if pattern.fullmatch(candidate):
                    ignored = not negated
        return ignored

    @staticmethod
    def _compile(pattern: str, anchored: bool) -> re.Pattern[str]:
        output = ""
        index = 0
        while index < len(pattern):
            char = pattern[index]
            if char == "*" and index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    output += "(?:.*/)?"
                    index += 1
                else:
                    output += ".*"
                continue
            if char == "*":
                output += "[^/]*"
            elif char == "?":
                output += "[^/]"
            else:
                output += re.escape(char)
            index += 1
        if "/" not in pattern and not anchored:
            output = r"(?:.*/)?" + output
        elif not anchored:
            output = r"(?:.*/)?" + output
        return re.compile(output)
