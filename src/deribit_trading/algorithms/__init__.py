"""Placement algorithm Protocol and registry.

To add a new algorithm:
1. Create a new .py file in this directory
2. Implement a class satisfying PlacementAlgorithm Protocol
3. Add it to ALGORITHM_REGISTRY below
"""

from __future__ import annotations

import warnings
from typing import Any, Protocol, runtime_checkable

from ..smart_order.types import Action, MarketSnapshot

# Old short names → new fully-qualified registry keys. Looking up an alias emits
# a DeprecationWarning and resolves to the legacy implementation. Drop after one
# minor version once REST / MCP / service callers migrate to intent path.
LEGACY_ALIASES: dict[str, str] = {
    "tick-chaser": "legacy:tick-chaser",
    "timed-escalation": "legacy:timed-escalation",
}


@runtime_checkable
class PlacementAlgorithm(Protocol):
    """Interface that all placement algorithms must satisfy.

    Algorithms are pure: they receive a MarketSnapshot and return an Action.
    They must not access WebSocket, database, or any async infrastructure.
    """

    name: str

    def initial_price(self, snapshot: MarketSnapshot) -> float:
        """Compute the initial order price."""
        ...

    def on_update(self, snapshot: MarketSnapshot) -> Action:
        """Called on each market data update. Return an Action."""
        ...

    def on_fill(self, fill_price: float, fill_amount: float) -> None:
        """Called when a (partial) fill occurs. Optional for learning."""
        ...


# ── Registry ────────────────────────────────────────────────────────

ALGORITHM_REGISTRY: dict[str, type] = {}


def register_algorithm(cls: type) -> type:
    """Decorator to register an algorithm class."""
    ALGORITHM_REGISTRY[cls.name] = cls
    return cls


def get_algorithm(name: str, params: dict[str, Any] | None = None) -> PlacementAlgorithm:
    """Instantiate a registered algorithm by name. Resolves legacy short names."""
    if name in LEGACY_ALIASES:
        new_name = LEGACY_ALIASES[name]
        warnings.warn(
            f"Algorithm name '{name}' is deprecated; use '{new_name}' or the "
            f"intent-driven SmartOrderConfig (intent='standard'|'urgent').",
            DeprecationWarning,
            stacklevel=2,
        )
        name = new_name

    if name not in ALGORITHM_REGISTRY:
        available = ", ".join(ALGORITHM_REGISTRY.keys()) or "(none)"
        raise ValueError(f"Unknown algorithm '{name}'. Available: {available}")

    cls = ALGORITHM_REGISTRY[name]
    return cls(**(params or {}))


def list_algorithms() -> list[str]:
    """Return all registered algorithm names."""
    return list(ALGORITHM_REGISTRY.keys())
