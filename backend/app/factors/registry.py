"""The factor registry.

Every factor is a pure function of a :class:`Panel`, registered with metadata
the UI reads directly. Adding a factor means writing one function and
decorating it -- precompute, the screener, the strategy DSL and the research
page all pick it up automatically.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from app.factors.panel import Panel

Category = Literal["value", "quality", "growth", "momentum", "risk", "revisions", "ownership"]

ComputeFn = Callable[[Panel], pd.Series]


@dataclass(frozen=True)
class Factor:
    name: str
    label: str
    category: Category
    description: str
    compute: ComputeFn
    # Whether a *higher raw value* is a better company. Scoring flips the sign
    # when it is not, so every stored z-score reads "higher is better".
    higher_is_better: bool = True
    # Score within sector as well as globally. Leverage and margins are
    # sector-bound (a bank's debt/equity is not a utility's); price momentum is
    # not, so blending is per-factor rather than global.
    sector_neutral: bool = True
    unit: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


_REGISTRY: dict[str, Factor] = {}


def register(
    name: str,
    label: str,
    category: Category,
    description: str,
    *,
    higher_is_better: bool = True,
    sector_neutral: bool = True,
    unit: str = "",
    tags: tuple[str, ...] = (),
) -> Callable[[ComputeFn], ComputeFn]:
    def decorator(fn: ComputeFn) -> ComputeFn:
        if name in _REGISTRY:
            raise ValueError(f"Duplicate factor name: {name}")
        _REGISTRY[name] = Factor(
            name=name,
            label=label,
            category=category,
            description=description,
            compute=fn,
            higher_is_better=higher_is_better,
            sector_neutral=sector_neutral,
            unit=unit,
            tags=tags,
        )
        return fn

    return decorator


def all_factors() -> dict[str, Factor]:
    _load_all()
    return dict(_REGISTRY)


def get_factor(name: str) -> Factor:
    _load_all()
    if name not in _REGISTRY:
        raise KeyError(f"Unknown factor: {name}")
    return _REGISTRY[name]


def factors_by_category() -> dict[str, list[Factor]]:
    out: dict[str, list[Factor]] = {}
    for factor in all_factors().values():
        out.setdefault(factor.category, []).append(factor)
    for group in out.values():
        group.sort(key=lambda f: f.label)
    return out


_loaded = False


def _load_all() -> None:
    """Import the factor modules so their decorators run."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from app.factors import (  # noqa: F401
        growth,
        momentum,
        ownership,
        quality,
        revisions,
        risk,
        value,
    )
