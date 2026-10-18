"""External product-data sources for the smart lookup (manufacturer, official agent, licensed databases).

A provider returns *candidates* — never a saved entry — each with its source URL and a confidence, so the employee
reviews before anything is stored. No provider ships enabled: a licensed database (e.g. Icecat) needs the company's
own account and terms, so it is registered only when configured. Tests register a fake provider.
"""
from __future__ import annotations

from typing import Any, Protocol


class Provider(Protocol):
    name: str

    def lookup(self, query: str) -> list[dict[str, Any]]:  # pragma: no cover - interface
        ...


_REGISTRY: list[Provider] = []


def register(provider: Provider) -> None:
    if all(p.name != provider.name for p in _REGISTRY):
        _REGISTRY.append(provider)


def unregister(name: str) -> None:
    _REGISTRY[:] = [p for p in _REGISTRY if p.name != name]


def active() -> list[Provider]:
    return list(_REGISTRY)
