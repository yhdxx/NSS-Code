from __future__ import annotations

from dataclasses import dataclass


PASTE_COLLAPSE_THRESHOLD = 500
PASTE_MARKER_TEMPLATE = "[Pasted Content {chars} chars]"


@dataclass(frozen=True)
class InputSegment:
    text: str
    kind: str = "text"

    @property
    def is_paste(self) -> bool:
        return self.kind == "paste"

    @property
    def display_text(self) -> str:
        if self.is_paste:
            return paste_marker(self.text) if should_collapse_paste(self.text) else self.text
        return self.text


class InputDocument:
    """Editable input buffer where only collapsed pasted blocks are atomic tokens."""

    def __init__(self, segments: list[InputSegment] | None = None) -> None:
        self.segments = _merge_text_segments(segments or [])

    @classmethod
    def from_text(cls, text: str) -> "InputDocument":
        return cls([InputSegment(text=text)]) if text else cls()

    def copy(self) -> "InputDocument":
        return InputDocument(list(self.segments))

    @property
    def text(self) -> str:
        return "".join(segment.text for segment in self.segments)

    @property
    def display_text(self) -> str:
        return "".join(segment.display_text for segment in self.segments)

    def display_index_for_text_index(self, index: int) -> int:
        index = clamp_index(index, len(self.text))
        text_position = 0
        display_position = 0
        for segment in self.segments:
            start = text_position
            end = start + len(segment.text)
            if index <= start:
                return display_position
            if index < end:
                if is_collapsed_paste_segment(segment):
                    return display_position
                return display_position + (index - start)
            text_position = end
            display_position += len(segment.display_text)
        return display_position

    def text_index_for_display_index(self, index: int) -> int:
        index = clamp_index(index, len(self.display_text))
        text_position = 0
        display_position = 0
        for segment in self.segments:
            display_start = display_position
            display_end = display_start + len(segment.display_text)
            text_start = text_position
            text_end = text_start + len(segment.text)
            if index <= display_start:
                return text_start
            if index < display_end:
                if is_collapsed_paste_segment(segment):
                    midpoint = display_start + len(segment.display_text) / 2
                    return text_start if index < midpoint else text_end
                return text_start + (index - display_start)
            display_position = display_end
            text_position = text_end
        return text_position

    def normalize_cursor(self, index: int, *, direction: int = 1) -> int:
        index = clamp_index(index, len(self.text))
        for start, end, segment in self._segments_with_ranges():
            if not is_collapsed_paste_segment(segment) or not (start < index < end):
                continue
            return end if direction >= 0 else start
        return index

    def move_cursor(self, index: int, delta: int) -> int:
        if delta == 0:
            return self.normalize_cursor(index)
        target = clamp_index(index + delta, len(self.text))
        return self.normalize_cursor(target, direction=delta)

    def insert_text(self, index: int, text: str) -> tuple["InputDocument", int]:
        if not text:
            return self.copy(), self.normalize_cursor(index)
        return self._insert_segment(index, InputSegment(text=text, kind="text"))

    def insert_paste(self, index: int, text: str) -> tuple["InputDocument", int]:
        if not text:
            return self.copy(), self.normalize_cursor(index)
        return self._insert_segment(index, InputSegment(text=text, kind="paste"))

    def delete_previous(self, index: int) -> tuple["InputDocument", int]:
        index = self.normalize_cursor(index, direction=-1)
        if index <= 0:
            return self.copy(), index
        start = index - 1
        for segment_start, segment_end, segment in self._segments_with_ranges():
            if is_collapsed_paste_segment(segment) and segment_start < index <= segment_end:
                start = segment_start
                index = segment_end
                break
        return self.delete_range(start, index)

    def delete_at(self, index: int) -> tuple["InputDocument", int]:
        index = self.normalize_cursor(index, direction=1)
        if index >= len(self.text):
            return self.copy(), index
        end = index + 1
        for segment_start, segment_end, segment in self._segments_with_ranges():
            if is_collapsed_paste_segment(segment) and segment_start <= index < segment_end:
                index = segment_start
                end = segment_end
                break
        return self.delete_range(index, end)

    def delete_range(self, start: int, end: int) -> tuple["InputDocument", int]:
        text_length = len(self.text)
        start = clamp_index(start, text_length)
        end = clamp_index(end, text_length)
        if start > end:
            start, end = end, start
        if start == end:
            return self.copy(), start
        start, end = self._expand_range_for_paste(start, end)
        segments: list[InputSegment] = []
        for segment_start, segment_end, segment in self._segments_with_ranges():
            if segment_end <= start or segment_start >= end:
                segments.append(segment)
                continue
            if is_collapsed_paste_segment(segment):
                continue
            left_keep = max(0, start - segment_start)
            right_keep = max(0, segment_end - end)
            if left_keep:
                segments.append(InputSegment(segment.text[:left_keep], segment.kind))
            if right_keep:
                segments.append(InputSegment(segment.text[len(segment.text) - right_keep :], segment.kind))
        return InputDocument(segments), start

    def styled_display_text(
        self,
        *,
        text_style: str = "",
        paste_style: str = "",
        reset_style: str = "",
    ) -> str:
        if not text_style and not paste_style:
            return self.display_text
        parts: list[str] = []
        for _start, _end, segment in self._segments_with_ranges():
            style = paste_style if segment.is_paste and should_collapse_paste(segment.text) else text_style
            if style:
                parts.append(style)
            parts.append(segment.display_text)
            if style and reset_style:
                parts.append(reset_style)
        return "".join(parts)

    def _insert_segment(self, index: int, new_segment: InputSegment) -> tuple["InputDocument", int]:
        index = self.normalize_cursor(index)
        segments: list[InputSegment] = []
        inserted = False
        for start, end, segment in self._segments_with_ranges():
            if not inserted and index <= start:
                segments.append(new_segment)
                inserted = True
            if is_collapsed_paste_segment(segment) or not (start < index < end):
                segments.append(segment)
                continue
            split = index - start
            segments.append(InputSegment(segment.text[:split], segment.kind))
            if not inserted:
                segments.append(new_segment)
                inserted = True
            segments.append(InputSegment(segment.text[split:], segment.kind))
        if not inserted:
            segments.append(new_segment)
        return InputDocument(segments), index + len(new_segment.text)

    def _expand_range_for_paste(self, start: int, end: int) -> tuple[int, int]:
        for segment_start, segment_end, segment in self._segments_with_ranges():
            if not is_collapsed_paste_segment(segment):
                continue
            if start < segment_end and end > segment_start:
                start = min(start, segment_start)
                end = max(end, segment_end)
        return start, end

    def _segments_with_ranges(self) -> list[tuple[int, int, InputSegment]]:
        ranges: list[tuple[int, int, InputSegment]] = []
        position = 0
        for segment in self.segments:
            start = position
            end = start + len(segment.text)
            ranges.append((start, end, segment))
            position = end
        return ranges


def paste_marker(text: str) -> str:
    return PASTE_MARKER_TEMPLATE.format(chars=len(text))


def should_collapse_paste(text: str) -> bool:
    return len(text) > PASTE_COLLAPSE_THRESHOLD


def is_collapsed_paste_segment(segment: InputSegment) -> bool:
    return segment.is_paste and should_collapse_paste(segment.text)


def clamp_index(index: int, length: int) -> int:
    return max(0, min(index, length))


def _merge_text_segments(segments: list[InputSegment]) -> list[InputSegment]:
    merged: list[InputSegment] = []
    for segment in segments:
        if not segment.text:
            continue
        if merged and not merged[-1].is_paste and not segment.is_paste:
            merged[-1] = InputSegment(merged[-1].text + segment.text, "text")
        else:
            merged.append(segment)
    return merged
