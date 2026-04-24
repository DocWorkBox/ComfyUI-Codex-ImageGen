from __future__ import annotations

import json


class NoOpProgress:
    def update_absolute(self, value: int, total: int | None = None, preview=None) -> None:
        pass


def create_progress(total: int = 100):
    try:
        from comfy.utils import ProgressBar

        return ProgressBar(total)
    except Exception:
        return NoOpProgress()


def update_progress(progress, value: int) -> None:
    try:
        progress.update_absolute(value)
    except TypeError:
        progress.update_absolute(value, 100)
    except Exception:
        pass


def progress_for_jsonl_event(line: str) -> int | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None

    event_type = event.get("type")
    if event_type == "thread.started":
        return 20
    if event_type == "turn.started":
        return 35

    item = event.get("item")
    if isinstance(item, dict):
        item_type = item.get("type")
        text = item.get("text") if isinstance(item.get("text"), str) else ""
        if item_type == "agent_message":
            if "imagegen" in text.lower():
                return 55
            return 45
        if item_type == "command_execution":
            status = item.get("status")
            if status == "in_progress":
                return 70
            if status == "completed":
                return 80

    if event_type == "turn.completed":
        return 90
    if event_type == "error":
        return 50
    return None
