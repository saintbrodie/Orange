import json

from app.api import status
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


def test_record_completion_can_update_history_without_replaying_terminal_event(monkeypatch):
    updates = []
    events = []

    monkeypatch.setattr(status, "update_usage_status", lambda prompt_id, state: updates.append((prompt_id, state)))
    monkeypatch.setattr(status, "emit_terminal_event_once", lambda *args: events.append(args))

    status._record_completion("old-prompt-id", announce=False)

    assert updates == [("old-prompt-id", "completed")]
    assert events == []


def test_record_completion_announces_live_job_once(monkeypatch):
    updates = []
    events = []

    monkeypatch.setattr(status, "update_usage_status", lambda prompt_id, state: updates.append((prompt_id, state)))
    monkeypatch.setattr(status, "emit_terminal_event_once", lambda *args: events.append(args))

    status._record_completion("1234567890abcdef")

    assert updates == [("1234567890abcdef", "completed")]
    assert events == [
        (
            "generation-complete:1234567890abcdef",
            "generation",
            "complete",
            "Generation 12345678 complete",
        )
    ]
