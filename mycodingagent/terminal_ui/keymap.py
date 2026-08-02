from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypeAlias


KEYMAP_PATH_ENV = "MYCODINGAGENT_KEYMAP"

InputAction: TypeAlias = str
Keymap: TypeAlias = dict[InputAction, tuple[str, ...]]

DEFAULT_KEYMAP: Keymap = {
    "submit": ("enter",),
    "newline": ("ctrl+j",),
    "select_all": ("alt+a",),
    "copy_or_interrupt": ("ctrl+c",),
    "paste": ("ctrl+v",),
    "indent": ("tab",),
    "unindent": ("shift+tab",),
    "line_start": ("ctrl+a", "home"),
    "line_end": ("ctrl+e", "end"),
    "delete_line_start": ("ctrl+u",),
    "delete_line_end": ("ctrl+k",),
    "delete_word_backward": ("alt+backspace",),
    "escape": ("esc",),
    "backspace": ("backspace",),
    "delete": ("delete",),
    "left": ("left",),
    "right": ("right",),
    "up": ("up",),
    "down": ("down",),
}

SUPPORTED_ACTIONS = frozenset(DEFAULT_KEYMAP)


def load_keymap(path: str | os.PathLike[str] | None = None) -> Keymap:
    """Load a user keymap override without making terminal input depend on app config."""
    loaded = dict(DEFAULT_KEYMAP)
    config_path = Path(path).expanduser() if path else _env_keymap_path()
    if config_path is None or not config_path.exists():
        return loaded
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return loaded
    if not isinstance(raw, dict):
        return loaded
    candidate = dict(loaded)
    for action, bindings in raw.items():
        if action not in SUPPORTED_ACTIONS:
            continue
        normalized = normalize_bindings(bindings)
        if normalized:
            candidate[action] = normalized
    return candidate if not has_binding_conflicts(candidate) else loaded


def action_for_key(keymap: Keymap, key: str) -> str:
    normalized = normalize_key(key)
    for action, bindings in keymap.items():
        if normalized in bindings:
            return action
    return ""


def normalize_bindings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [item for item in value if isinstance(item, str)]
    else:
        return ()
    normalized = tuple(dict.fromkeys(normalize_key(item) for item in items if normalize_key(item)))
    return normalized


def normalize_key(key: str) -> str:
    return "+".join(part.strip().lower() for part in key.replace(" ", "").split("+") if part.strip())


def has_binding_conflicts(keymap: Keymap) -> bool:
    seen: dict[str, str] = {}
    for action, bindings in keymap.items():
        for binding in bindings:
            if binding in seen and seen[binding] != action:
                return True
            seen[binding] = action
    return False


def _env_keymap_path() -> Path | None:
    value = os.getenv(KEYMAP_PATH_ENV, "").strip()
    if not value:
        return None
    return Path(value).expanduser()
