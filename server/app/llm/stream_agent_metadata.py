"""Merge live agent evidence without losing it to preparation metadata."""

from __future__ import annotations

from typing import Any


def merge_stream_agent_metadata(
    prepared: dict[str, Any], live: dict[str, Any], *, preserve_failure: bool = False,
) -> dict[str, Any]:
    merged = {**prepared, **live}
    if preserve_failure:
        merged.update(prepared)
    else:
        # Empty final fields must not erase useful preparation descriptions.
        for key, value in live.items():
            if value is None and key in prepared:
                merged[key] = prepared[key]
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for source in (prepared, live):
        for event in source.get("tool_events") or []:
            if not isinstance(event, dict):
                continue
            identity = (
                str(event.get("type") or ""),
                str(event.get("id") or ""),
                str(event.get("name") or ""),
                str(event.get("step") or ""),
            )
            if identity in seen:
                continue
            seen.add(identity)
            events.append(dict(event))
    merged["tool_events"] = events
    merged["steps"] = live.get("steps") or prepared.get("steps") or []
    return merged
