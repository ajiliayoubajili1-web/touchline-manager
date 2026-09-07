"""Position-weighted overall ratings.

A player's displayed overall rating is a weighted average of their attributes,
with weights depending on the position they play. The same attributes therefore
produce different useful ratings at different positions, which makes versatile
players genuinely valuable in different roles.
"""

from __future__ import annotations

from manager.core.enums import Position

_WEIGHTS: dict[Position, dict[str, float]] = {
    Position.GK: {"goalkeeper": 0.80, "physical": 0.10, "defending": 0.05, "passing": 0.05},
    Position.LB: {"defending": 0.45, "physical": 0.25, "pace": 0.20, "passing": 0.10},
    Position.RB: {"defending": 0.45, "physical": 0.25, "pace": 0.20, "passing": 0.10},
    Position.CB: {"defending": 0.55, "physical": 0.30, "pace": 0.10, "passing": 0.05},
    Position.WB: {"defending": 0.35, "pace": 0.25, "physical": 0.15, "passing": 0.15, "dribbling": 0.08, "shooting": 0.02},
    Position.DM: {"defending": 0.40, "passing": 0.30, "physical": 0.20, "pace": 0.10},
    Position.CM: {"passing": 0.40, "dribbling": 0.20, "defending": 0.15, "physical": 0.10, "pace": 0.10, "shooting": 0.05},
    Position.AM: {"passing": 0.35, "dribbling": 0.25, "shooting": 0.20, "pace": 0.10, "defending": 0.05, "physical": 0.05},
    Position.LM: {"passing": 0.25, "dribbling": 0.25, "pace": 0.20, "shooting": 0.15, "defending": 0.05, "physical": 0.10},
    Position.RM: {"passing": 0.25, "dribbling": 0.25, "pace": 0.20, "shooting": 0.15, "defending": 0.05, "physical": 0.10},
    Position.LW: {"pace": 0.25, "dribbling": 0.25, "shooting": 0.25, "passing": 0.15, "defending": 0.05, "physical": 0.05},
    Position.RW: {"pace": 0.25, "dribbling": 0.25, "shooting": 0.25, "passing": 0.15, "defending": 0.05, "physical": 0.05},
    Position.CF: {"shooting": 0.35, "passing": 0.20, "dribbling": 0.20, "pace": 0.15, "physical": 0.10},
    Position.ST: {"shooting": 0.40, "pace": 0.20, "physical": 0.20, "dribbling": 0.15, "passing": 0.05},
}

ATTRIBUTE_NAMES = (
    "pace",
    "shooting",
    "passing",
    "dribbling",
    "defending",
    "physical",
    "goalkeeper",
)


def position_weights(position: Position) -> dict[str, float]:
    """Return a copy of the attribute weights for ``position``."""
    return dict(_WEIGHTS[position])


def overall_rating(attributes, position: Position) -> int:
    """Compute the weighted overall rating of ``attributes`` at ``position``."""
    weights = _WEIGHTS[position]
    total = sum(
        float(getattr(attributes, name)) * weight for name, weight in weights.items()
    )
    return int(round(total))