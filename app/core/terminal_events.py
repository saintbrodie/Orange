from __future__ import annotations

import json
from collections import deque

_PREFIX = "ORANGE_EVENT "
_SEEN_LIMIT = 256
_seen_order: deque[str] = deque()
_seen_keys: set[str] = set()


def emit_terminal_event(kind: str, state: str, message: str) -> None:
    payload = {
        "kind": str(kind or "activity")[:32],
        "state": str(state or "info")[:32],
        "message": " ".join(str(message or "").split())[:240],
    }
    print(_PREFIX + json.dumps(payload, separators=(",", ":")), flush=True)


def emit_terminal_event_once(key: str, kind: str, state: str, message: str) -> None:
    key = str(key or "")[:256]
    if key in _seen_keys:
        return
    _seen_keys.add(key)
    _seen_order.append(key)
    while len(_seen_order) > _SEEN_LIMIT:
        old = _seen_order.popleft()
        _seen_keys.discard(old)
    emit_terminal_event(kind, state, message)
