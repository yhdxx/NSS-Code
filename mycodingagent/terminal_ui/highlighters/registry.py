from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

try:
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.text import Text
except ImportError:  # pragma: no cover - only relevant before dependencies are installed
    Markdown = None  # type: ignore[assignment]
    Syntax = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]


LanguageId = Literal[
    "markdown",
    "python",
    "java",
    "cpp",
    "c",
    "go",
    "rust",
    "javascript",
    "typescript",
    "html",
    "text",
]


LANGUAGE_ALIASES: dict[str, LanguageId] = {
    "md": "markdown",
    "markdown": "markdown",
    "py": "python",
    "python": "python",
    "java": "java",
    "cpp": "cpp",
    "c++": "cpp",
    "cxx": "cpp",
    "cc": "cpp",
    "hpp": "cpp",
    "c": "c",
    "h": "c",
    "go": "go",
    "golang": "go",
    "rs": "rust",
    "rust": "rust",
    "js": "javascript",
    "jsx": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "typescript": "typescript",
    "html": "html",
    "htm": "html",
    "xml": "html",
    "text": "text",
    "txt": "text",
}

EXTENSION_LANGUAGES: dict[str, LanguageId] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".py": "python",
    ".pyw": "python",
    ".java": "java",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".c": "c",
    ".h": "c",
    ".go": "go",
    ".rs": "rust",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".html": "html",
    ".htm": "html",
    ".xml": "html",
    ".txt": "text",
}

SINGLE_FENCE_RE = re.compile(r"\A\s*```(?P<lang>[A-Za-z0-9_+\-.#]*)[^\n]*\n(?P<body>.*?)\n```\s*\Z", re.S)
ANY_FENCE_RE = re.compile(r"```(?P<lang>[A-Za-z0-9_+\-.#]*)")


class TerminalHighlighter(Protocol):
    language: LanguageId

    def render(self, text: str, *, style: str = "bright_white") -> Any:
        ...


@dataclass(frozen=True)
class SyntaxHighlighter:
    language: LanguageId
    lexer: str

    def render(self, text: str, *, style: str = "bright_white") -> Any:
        if Syntax is None:
            return _plain_text(text, style=style)
        return Syntax(
            text,
            self.lexer,
            theme="ansi_dark",
            background_color="default",
            word_wrap=True,
            line_numbers=False,
        )


@dataclass(frozen=True)
class MarkdownHighlighter:
    language: LanguageId = "markdown"

    def render(self, text: str, *, style: str = "markdown.base") -> Any:
        if Markdown is None:
            return _plain_text(text, style="bright_white")
        return Markdown(text, style=style, code_theme="ansi_dark")


@dataclass(frozen=True)
class DefaultHighlighter:
    language: LanguageId = "text"

    def render(self, text: str, *, style: str = "bright_white") -> Any:
        return _plain_text(text, style=style)


class PythonHighlighter(SyntaxHighlighter):
    def __init__(self) -> None:
        super().__init__("python", "python")


class JavaHighlighter(SyntaxHighlighter):
    def __init__(self) -> None:
        super().__init__("java", "java")


class CppHighlighter(SyntaxHighlighter):
    def __init__(self) -> None:
        super().__init__("cpp", "cpp")


class CHighlighter(SyntaxHighlighter):
    def __init__(self) -> None:
        super().__init__("c", "c")


class GoHighlighter(SyntaxHighlighter):
    def __init__(self) -> None:
        super().__init__("go", "go")


class RustHighlighter(SyntaxHighlighter):
    def __init__(self) -> None:
        super().__init__("rust", "rust")


class JavaScriptHighlighter(SyntaxHighlighter):
    def __init__(self) -> None:
        super().__init__("javascript", "javascript")


class TypeScriptHighlighter(SyntaxHighlighter):
    def __init__(self) -> None:
        super().__init__("typescript", "typescript")


class HtmlHighlighter(SyntaxHighlighter):
    def __init__(self) -> None:
        super().__init__("html", "html")


HIGHLIGHTERS: dict[LanguageId, TerminalHighlighter] = {
    "markdown": MarkdownHighlighter(),
    "python": PythonHighlighter(),
    "java": JavaHighlighter(),
    "cpp": CppHighlighter(),
    "c": CHighlighter(),
    "go": GoHighlighter(),
    "rust": RustHighlighter(),
    "javascript": JavaScriptHighlighter(),
    "typescript": TypeScriptHighlighter(),
    "html": HtmlHighlighter(),
    "text": DefaultHighlighter(),
}


def detect_language(text: str, *, file_path: str = "", declared_language: str = "") -> LanguageId:
    declared = normalize_language(declared_language)
    if declared != "text":
        return declared

    extension_language = language_from_path(file_path)
    if extension_language != "text":
        return extension_language

    single_fence = SINGLE_FENCE_RE.match(text)
    if single_fence is not None:
        return normalize_language(single_fence.group("lang"))

    shebang_language = language_from_shebang(text)
    if shebang_language != "text":
        return shebang_language

    if looks_like_markdown(text):
        return "markdown"

    stripped = text.strip()
    if not stripped:
        return "text"
    if re.search(r"^\s*package\s+main\b", stripped, re.M):
        return "go"
    if re.search(r"^\s*fn\s+main\s*\(", stripped, re.M) or "println!" in stripped:
        return "rust"
    if "#include" in stripped:
        return "cpp" if re.search(r"\b(std::|class|template\s*<)", stripped) else "c"
    if re.search(r"\bpublic\s+class\s+\w+", stripped):
        return "java"
    if re.search(r"\b(def|class)\s+\w+|\bimport\s+\w+|from\s+\w+\s+import\b", stripped):
        return "python"
    if re.search(r"\b(interface|type)\s+\w+\s*[={]|\bconst\s+\w+\s*:\s*\w+", stripped):
        return "typescript"
    if re.search(r"\b(function|const|let|var)\s+\w+|=>", stripped):
        return "javascript"
    if re.search(r"<(!doctype\s+html|html|div|span|body|script|style)\b", stripped, re.I):
        return "html"
    return "text"


def highlight_for_terminal(
    text: str,
    *,
    file_path: str = "",
    declared_language: str = "",
    style: str = "bright_white",
) -> Any:
    language = detect_language(text, file_path=file_path, declared_language=declared_language)
    highlighter = HIGHLIGHTERS.get(language, HIGHLIGHTERS["text"])
    if language == "markdown":
        return highlighter.render(text, style="markdown.base")
    return highlighter.render(text, style=style)


def normalize_language(language: str) -> LanguageId:
    value = language.strip().lower()
    if not value:
        return "text"
    value = value.removeprefix(".")
    return LANGUAGE_ALIASES.get(value, "text")


def language_from_path(file_path: str) -> LanguageId:
    if not file_path:
        return "text"
    suffix = Path(file_path).suffix.lower()
    return EXTENSION_LANGUAGES.get(suffix, "text")


def language_from_shebang(text: str) -> LanguageId:
    first_line = text.splitlines()[0].lower() if text else ""
    if not first_line.startswith("#!"):
        return "text"
    if "python" in first_line:
        return "python"
    if "node" in first_line:
        return "javascript"
    return "text"


def looks_like_markdown(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if ANY_FENCE_RE.search(stripped):
        return True
    markdown_patterns = (
        r"^#{1,6}\s+\S+",
        r"^\s*[-*+]\s+\S+",
        r"^\s*\d+\.\s+\S+",
        r"^\s*>\s+\S+",
        r"\[[^\]]+\]\([^)]+\)",
        r"^\|.+\|\s*$",
    )
    return any(re.search(pattern, stripped, re.M) for pattern in markdown_patterns)


def _plain_text(text: str, *, style: str) -> Any:
    if Text is None:
        return text
    return Text(text, style=style)
