from __future__ import annotations

import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt
from markdown_it.token import Token as MarkdownToken
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.utils import get_cwidth
from pygments import lex
from pygments.lexers import ClassNotFound, get_lexer_by_name
from pygments.token import Comment, Keyword, Name, Number, Operator, Punctuation, String, Token


MAX_HIGHLIGHT_BYTES = 512 * 1024
MAX_HIGHLIGHT_LINES = 10_000
MAX_HIGHLIGHT_LINE_BYTES = 4 * 1024
_REFERENCE_LINK_DEFINITION = re.compile(r"^\s*\[[^]]+\]:\s+\S+", re.M)
_FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})")
_FENCE_CLOSE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*(?:\r?\n)?$")


class MarkdownStreamCollector:
    """Accumulate provider deltas and expose newline-terminated source only."""

    def __init__(self) -> None:
        self._source = ""
        self._committed_len = 0

    @property
    def source(self) -> str:
        return self._source

    @property
    def committed_source(self) -> str:
        return self._source[: self._committed_len]

    def push_delta(self, text: str) -> None:
        self._source += text

    def commit_complete_source(self) -> bool:
        newline = self._source.rfind("\n")
        if newline < self._committed_len:
            return False
        committed_len = newline + 1
        if committed_len == self._committed_len:
            return False
        self._committed_len = committed_len
        return True

    def finalize(self) -> str:
        if self._source and self._committed_len < len(self._source):
            self._committed_len = len(self._source)
        return self._source

    def clear(self) -> None:
        self._source = ""
        self._committed_len = 0


@dataclass
class StreamingMarkdownRenderer:
    """Keep completed Markdown blocks stable while re-rendering the active tail."""

    _parser: MarkdownIt = field(default_factory=lambda: MarkdownIt("commonmark").enable("table"))
    _stable_source: str = ""
    _stable_fragments: StyleAndTextTuples = field(default_factory=list)
    _tail_fragments: StyleAndTextTuples = field(default_factory=list)

    def update(self, source: str) -> None:
        stable_end = _stable_prefix_end(self._parser.parse(source), source)
        if _REFERENCE_LINK_DEFINITION.search(source):
            stable_end = 0
        stable_source = source[:stable_end]
        tail_source = source[stable_end:]
        if not stable_source.startswith(self._stable_source):
            self._stable_fragments = _render_markdown(self._parser, stable_source)
        elif stable_source != self._stable_source:
            self._stable_fragments.extend(
                _render_markdown(self._parser, stable_source[len(self._stable_source) :])
            )
        self._stable_source = stable_source
        self._tail_fragments = _render_markdown(self._parser, tail_source)

    def preview(self, *, max_chars: int) -> StyleAndTextTuples:
        return _truncate_tail(
            [*self._stable_fragments, *self._tail_fragments],
            max_chars=max_chars,
        )

    def reset(self) -> None:
        self._stable_source = ""
        self._stable_fragments = []
        self._tail_fragments = []


def _stable_prefix_end(tokens: list[MarkdownToken], source: str) -> int:
    starts = [
        token.map[0]
        for token in tokens
        if token.level == 0 and token.block and token.map is not None
    ]
    if len(starts) < 2:
        return 0
    return _line_offsets(source)[starts[-1]]


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    for index, character in enumerate(source):
        if character == "\n":
            offsets.append(index + 1)
    return offsets


def _render_markdown(parser: MarkdownIt, source: str) -> StyleAndTextTuples:
    if not source:
        return []
    tokens = parser.parse(source)
    lines = source.splitlines(keepends=True)
    fragments: StyleAndTextTuples = []
    list_stack: list[int | None] = []
    quote_depth = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "heading_open":
            inline = _next_inline(tokens, index)
            _append_prefix(fragments, quote_depth=quote_depth)
            fragments.extend(_render_inline(inline, "class:stream.heading"))
            _append_newline(fragments, count=2)
        elif token.type == "paragraph_open":
            inline = _next_inline(tokens, index)
            _append_prefix(fragments, quote_depth=quote_depth)
            fragments.extend(_render_inline(inline, "class:stream.text"))
            _append_newline(fragments, count=2)
        elif token.type == "blockquote_open":
            quote_depth += 1
        elif token.type == "blockquote_close":
            quote_depth = max(0, quote_depth - 1)
        elif token.type == "bullet_list_open":
            list_stack.append(None)
        elif token.type == "ordered_list_open":
            list_stack.append(int(token.attrGet("start") or "1"))
        elif token.type in {"bullet_list_close", "ordered_list_close"}:
            if list_stack:
                list_stack.pop()
        elif token.type == "list_item_open":
            _append_prefix(fragments, quote_depth=quote_depth, list_depth=len(list_stack))
            if list_stack and list_stack[-1] is not None:
                marker = f"{list_stack[-1]}. "
                list_stack[-1] += 1
            else:
                marker = "- "
            fragments.append(("class:stream.list_marker", marker))
        elif token.type == "fence":
            closed = _fence_is_closed(lines, token.map[0] if token.map else 0)
            code_style = "class:stream.code_block" if closed else "class:stream.code_pending"
            if closed:
                fragments.extend(_highlight_code(token.content, _fence_language(token.info)))
            else:
                fragments.append((code_style, token.content))
            _append_newline(fragments, count=1)
        elif token.type == "code_block":
            fragments.append(("class:stream.code_block", token.content))
            _append_newline(fragments, count=1)
        elif token.type == "hr":
            fragments.append(("class:stream.rule", "─" * 24))
            _append_newline(fragments, count=2)
        elif token.type == "table_open":
            end = _find_table_end(tokens, index)
            table_end_line = tokens[index].map[1] if tokens[index].map else len(lines)
            fragments.append(("class:stream.table", "".join(lines[tokens[index].map[0] : table_end_line])))
            _append_newline(fragments, count=1)
            index = end
        index += 1
    return fragments


def _next_inline(tokens: list[MarkdownToken], index: int) -> MarkdownToken:
    for token in tokens[index + 1 :]:
        if token.type == "inline":
            return token
    return MarkdownToken("inline", "", 0)


def _render_inline(token: MarkdownToken, base_style: str) -> StyleAndTextTuples:
    fragments: StyleAndTextTuples = []
    styles = [base_style]
    for child in token.children or []:
        if child.type == "text":
            fragments.append((styles[-1], child.content))
        elif child.type == "code_inline":
            fragments.append(("class:stream.inline_code", child.content))
        elif child.type in {"softbreak", "hardbreak"}:
            fragments.append((styles[-1], "\n"))
        elif child.type == "strong_open":
            styles.append("class:stream.strong")
        elif child.type == "em_open":
            styles.append("class:stream.emphasis")
        elif child.type == "s_open":
            styles.append("class:stream.strikethrough")
        elif child.type == "link_open":
            styles.append("class:stream.link")
        elif child.type in {"strong_close", "em_close", "s_close", "link_close"}:
            if len(styles) > 1:
                styles.pop()
        elif child.content:
            fragments.append((styles[-1], child.content))
    return fragments


def _append_prefix(fragments: StyleAndTextTuples, *, quote_depth: int, list_depth: int = 0) -> None:
    if quote_depth:
        fragments.append(("class:stream.quote", "> " * quote_depth))
    if list_depth > 1:
        fragments.append(("class:stream.text", "  " * (list_depth - 1)))


def _append_newline(fragments: StyleAndTextTuples, *, count: int) -> None:
    existing = 0
    if fragments:
        text = fragments[-1][1]
        existing = len(text) - len(text.rstrip("\n"))
    if existing < count:
        fragments.append(("class:stream.text", "\n" * (count - existing)))


def _fence_is_closed(lines: list[str], start_line: int) -> bool:
    if start_line >= len(lines):
        return False
    opening = _FENCE_OPEN.match(lines[start_line])
    if opening is None:
        return False
    marker = opening.group(1)
    for line in lines[start_line + 1 :]:
        closing = _FENCE_CLOSE.match(line)
        if closing and closing.group(1)[0] == marker[0] and len(closing.group(1)) >= len(marker):
            return True
    return False


def _fence_language(info: str) -> str:
    return re.split(r"[,\s]+", info.strip(), maxsplit=1)[0] if info.strip() else "text"


def _highlight_code(code: str, language: str) -> StyleAndTextTuples:
    if _exceeds_highlight_limits(code):
        return [("class:stream.code_block", code)]
    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        return [("class:stream.code_block", code)]
    return [(_pygments_style(token), text) for token, text in lex(code, lexer) if text]


def _exceeds_highlight_limits(code: str) -> bool:
    return (
        len(code.encode("utf-8")) > MAX_HIGHLIGHT_BYTES
        or code.count("\n") + 1 > MAX_HIGHLIGHT_LINES
        or any(len(line.encode("utf-8")) > MAX_HIGHLIGHT_LINE_BYTES for line in code.splitlines())
    )


def _pygments_style(token: Token) -> str:
    if token in Comment:
        return "class:stream.code_comment"
    if token in Keyword:
        return "class:stream.code_keyword"
    if token in String:
        return "class:stream.code_string"
    if token in Number:
        return "class:stream.code_number"
    if token in Name.Function or token in Name.Class:
        return "class:stream.code_name"
    if token in Operator or token in Punctuation:
        return "class:stream.code_operator"
    return "class:stream.code_block"


def _find_table_end(tokens: list[MarkdownToken], start: int) -> int:
    for index in range(start + 1, len(tokens)):
        if tokens[index].type == "table_close":
            return index
    return start


def _truncate_tail(fragments: StyleAndTextTuples, *, max_chars: int) -> StyleAndTextTuples:
    if max_chars <= 0:
        return []
    remaining = max_chars
    selected: list[tuple[str, str]] = []
    for style, text in reversed(fragments):
        if remaining <= 0:
            break
        if len(text) <= remaining:
            selected.append((style, text))
            remaining -= len(text)
        else:
            selected.append((style, text[-remaining:]))
            remaining = 0
    selected.reverse()
    if len(selected) < len(fragments) or remaining == 0 and sum(len(text) for _, text in fragments) > max_chars:
        return [("class:stream.muted", "...\n"), *selected]
    return selected


def visual_line_count(fragments: StyleAndTextTuples, *, columns: int) -> int:
    text = "".join(text for _style, text in fragments)
    return sum(max(1, (max(1, get_cwidth(line)) + columns - 1) // columns) for line in text.splitlines() or [""])
