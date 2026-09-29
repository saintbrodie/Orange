import json

from app.core import terminal_events


def _parse_event(line: str):
    assert line.startswith("ORANGE_EVENT ")
    return json.loads(line[len("ORANGE_EVENT "):])


def test_emit_terminal_event_is_structured_and_sanitized(capsys):
    terminal_events.emit_terminal_event("generation", "working", "  Starting\n generation   now  ")
    payload = _parse_event(capsys.readouterr().out.strip())
    assert payload == {
        "kind": "generation",
        "state": "working",
        "message": "Starting generation now",
    }


def test_emit_terminal_event_once_deduplicates(capsys):
    terminal_events._seen_keys.clear()
    terminal_events._seen_order.clear()
    terminal_events.emit_terminal_event_once("prompt-1", "generation", "complete", "Done")
    terminal_events.emit_terminal_event_once("prompt-1", "generation", "complete", "Done again")
    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(lines) == 1
    assert _parse_event(lines[0])["message"] == "Done"
