from __future__ import annotations

import re
from typing import Any

DEFAULT_LOCAL_OWNER_ID = "local-trainer"
DEFAULT_LOCAL_OWNER_NAME = "Local Trainer"
WINDOWS_WORKSPACE_ALIAS_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


# Stable identity fields on the records kept in structured memory. Lists of
# records are merged per item by one of these, so two sidecars appending to the
# same list keep both entries instead of the later writer flattening the list.
_STRUCTURED_ITEM_ID_KEYS = (
    "card_id",
    "asset_id",
    "task_id",
    "session_id",
    "event_id",
    "id",
    "concept",
    "key",
)


def _structured_item_identity(item: Any) -> tuple[str, str] | None:
    if not isinstance(item, dict):
        return None
    for key in _STRUCTURED_ITEM_ID_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value:
            return (key, value)
    return None


def _identities(items: list[Any]) -> dict[tuple[str, str], Any] | None:
    """Map list items by identity; ``None`` when the list has no stable ids."""
    mapped: dict[tuple[str, str], Any] = {}
    for item in items:
        identity = _structured_item_identity(item)
        if identity is None or identity in mapped:
            return None
        mapped[identity] = item
    return mapped


def _merge_unidentified_lists(base: list[Any], ours: list[Any], stored: list[Any]) -> list[Any]:
    """Three-way merge for value lists: keep stored entries, apply our delta.

    Entries this process removed are dropped from the stored list; entries it
    added are appended if absent. Entries another writer added are kept.
    """
    removed = [item for item in base if item not in ours]
    added = [item for item in ours if item not in base]
    merged = [item for item in stored if item not in removed]
    for item in added:
        if item not in merged:
            merged.append(item)
    return merged


def _merge_values(base: Any, ours: Any, stored: Any) -> Any:
    """Three-way merge of one JSON value: our changes win, theirs survive."""
    if isinstance(base, dict) and isinstance(ours, dict) and isinstance(stored, dict):
        merged = dict(stored)
        for key, value in ours.items():
            if key not in base or key not in stored:
                # New for this process, or missing from what was stored: the
                # exported state always carries every key, so a missing key is
                # a stripped record, not a deletion this process should honour.
                merged[key] = value
            elif base.get(key) != value:
                merged[key] = _merge_values(base.get(key), value, stored.get(key))
        return merged

    if isinstance(base, list) and isinstance(ours, list) and isinstance(stored, list):
        base_ids = _identities(base)
        ours_ids = _identities(ours)
        stored_ids = _identities(stored)
        if base_ids is None or ours_ids is None or stored_ids is None:
            return _merge_unidentified_lists(base, ours, stored)

        removed = set(base_ids) - set(ours_ids)
        merged = []
        for item in stored:
            identity = _structured_item_identity(item)
            if identity in removed:
                continue
            if identity in ours_ids and identity in base_ids:
                base_item = base_ids[identity]
                if item == base_item:
                    merged.append(ours_ids[identity])
                elif ours_ids[identity] == base_item:
                    merged.append(item)
                else:
                    # Both sides changed the same record: merge its fields.
                    merged.append(_merge_values(base_item, ours_ids[identity], item))
            else:
                # Another writer added it, or we both know it.
                merged.append(item if identity not in ours_ids else ours_ids[identity])
        for item in ours:
            identity = _structured_item_identity(item)
            # Only entries this process added are appended. An entry the base
            # already had and the stored list no longer carries was deleted by
            # the other writer, and that deletion stands.
            if identity not in base_ids and identity not in stored_ids:
                merged.append(item)
        return merged

    return ours


def _merge_structured_state(
    base: dict[str, Any],
    ours: dict[str, Any],
    stored: dict[str, Any],
) -> dict[str, Any]:
    """Keep another process's work while taking ours for what we changed.

    ``base`` is the state this process last exported, ``ours`` what it is
    writing now and ``stored`` what is in the database. Only the parts of
    ``ours`` that differ from ``base`` are applied, recursively into dicts and
    per record in id-bearing lists, so two sidecars editing one workspace do
    not erase each other. Dict keys are never removed: the exported state
    always carries every key (empty or null when unused), so an absent key
    here means "not known to this process", not "deleted".
    """
    return _merge_values(base, ours, stored)
