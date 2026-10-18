"""Read-only bridge from the analyzer's snapshot to the chat (never scans during a request, never invents steps)."""
from __future__ import annotations


def _snapshot():
    from modules.ai_tutor.analyzer import snapshot

    return snapshot.current_snapshot()  # None when missing or stale (sources changed since the scan)


def snapshot_key() -> str:
    snap = _snapshot()
    return f"{snap['meta']['created_at']}:{snap['meta']['fingerprint']}" if snap else "none"


def discovered_keys() -> set[tuple[str, str]] | None:
    """{(kind, id)} that really exist, or None when no fresh scan is available (then nothing is assumed missing)."""
    snap = _snapshot()
    return {(i["kind"], i["id"]) for i in snap["items"] if i["discovered"]} if snap else None


def is_discovered(ref: dict) -> bool:
    keys = discovered_keys()
    kind, ident = next(iter(ref.items()))
    return True if keys is None else (kind, ident) in keys


def feature_items(known_knowledge_ids: set[str], pages: set[str]) -> list[dict]:
    """Discovered user-facing actions that the knowledge registry does not cover yet (need a label to be findable)."""
    snap = _snapshot()
    if not snap:
        return []
    return [i for i in snap["items"]
            if i["kind"] == "action" and i["category"] == "feature" and i["discovered"] and not i["knowledge_registered"]
            and i["label_ar"] and i["page"] in pages and i["id"] not in known_knowledge_ids]
