"""Market valuation.

Produces a synthetic market value for a player from their rating, age, form and
remaining contract length. The formula is intentionally simple and monotonic so
it behaves predictably in tests; the transfer system (Phase 4) layers
negotiation and club-specific willingness on top of it.
"""

from __future__ import annotations

from math import exp


def _age_factor(age: float) -> float:
    peak = 25.0
    width = 6.0
    return exp(-(((age - peak) / width) ** 2))


def _form_factor(form: float) -> float:
    return 0.85 + (form / 100.0) * 0.30


def _contract_factor(years_left: float) -> float:
    years_left = max(0.0, min(years_left, 5.0))
    return 0.80 + (years_left / 5.0) * 0.40


def _potential_factor(potential: int, overall: int) -> float:
    room = max(0, potential - overall)
    return 1.0 + (room / 60.0) * 0.45


def market_value(
    overall: int,
    age: float,
    potential: int,
    form: float = 65.0,
    years_left: float = 2.0,
) -> int:
    """Estimate a player's market value in the game's currency units."""
    if overall <= 0:
        return 0
    base = overall ** 4.0
    value = (
        base
        * _age_factor(age)
        * _form_factor(form)
        * _contract_factor(years_left)
        * _potential_factor(potential, overall)
    )
    return int(value)


def wage_for_overall(overall: int) -> int:
    """Suggested weekly wage (currency/week) for a player's overall rating."""
    return max(1200, int((max(overall, 46) - 45) ** 2.2 * 14))