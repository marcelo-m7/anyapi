"""Dotted-path access and `{{ path }}` templating over the processor state."""

from __future__ import annotations

import json
import re
from typing import Any

_MISSING = object()
_TEMPLATE = re.compile(r"\{\{\s*([a-zA-Z0-9_.\-\[\]]+)\s*\}\}")
_SEGMENT = re.compile(r"[^.\[\]]+|\[\d+\]")


class PathError(ValueError):
    pass


def split_path(path: str) -> list[str | int]:
    if not isinstance(path, str) or not path.strip():
        raise PathError("Path must be a non-empty string")
    parts: list[str | int] = []
    for token in _SEGMENT.findall(path.strip()):
        if token.startswith("["):
            parts.append(int(token[1:-1]))
        elif token.isdigit():
            parts.append(int(token))
        else:
            if token in ("__proto__", "constructor", "__class__"):
                raise PathError(f"Illegal path segment: {token}")
            parts.append(token)
    if not parts:
        raise PathError(f"Invalid path: {path}")
    return parts


def get_path(data: Any, path: str, default: Any = None) -> Any:
    current = data
    for part in split_path(path):
        if isinstance(part, int) and isinstance(current, list):
            if -len(current) <= part < len(current):
                current = current[part]
                continue
            return default
        if isinstance(current, dict) and str(part) in current:
            current = current[str(part)]
            continue
        return default
    return current


def has_path(data: Any, path: str) -> bool:
    return get_path(data, path, _MISSING) is not _MISSING


def set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = split_path(path)
    current: Any = data
    for index, part in enumerate(parts[:-1]):
        nxt = parts[index + 1]
        if isinstance(current, list) and isinstance(part, int):
            while len(current) <= part:
                current.append(None)
            if not isinstance(current[part], (dict, list)):
                current[part] = [] if isinstance(nxt, int) else {}
            current = current[part]
            continue
        key = str(part)
        if not isinstance(current.get(key), (dict, list)):
            current[key] = [] if isinstance(nxt, int) else {}
        current = current[key]
    last = parts[-1]
    if isinstance(current, list) and isinstance(last, int):
        while len(current) <= last:
            current.append(None)
        current[last] = value
    elif isinstance(current, dict):
        current[str(last)] = value
    else:
        raise PathError(f"Cannot set {path}: parent is not an object")


def delete_path(data: dict[str, Any], path: str) -> None:
    parts = split_path(path)
    parent = get_path(data, ".".join(str(p) for p in parts[:-1])) if len(parts) > 1 else data
    last = parts[-1]
    if isinstance(parent, dict):
        parent.pop(str(last), None)
    elif isinstance(parent, list) and isinstance(last, int) and 0 <= last < len(parent):
        parent.pop(last)


def render_template(value: Any, state: dict[str, Any]) -> Any:
    """Render `{{ path }}` placeholders. A string that is exactly one placeholder keeps the raw type."""
    if isinstance(value, str):
        whole = _TEMPLATE.fullmatch(value.strip())
        if whole:
            return get_path(state, whole.group(1))

        def repl(match: re.Match[str]) -> str:
            resolved = get_path(state, match.group(1))
            if resolved is None:
                return ""
            if isinstance(resolved, (dict, list)):
                return json.dumps(resolved, ensure_ascii=False)
            if isinstance(resolved, bool):
                return "true" if resolved else "false"
            return str(resolved)

        return _TEMPLATE.sub(repl, value)
    if isinstance(value, dict):
        return {k: render_template(v, state) for k, v in value.items()}
    if isinstance(value, list):
        return [render_template(v, state) for v in value]
    return value
