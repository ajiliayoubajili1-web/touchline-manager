"""Career balance profiles.

Difficulty changes the starting conditions and how harshly the board judges
the manager. The values here are starting points that later phases can tune
independently.
"""

from __future__ import annotations

from dataclasses import dataclass

from manager.core.enums import Difficulty


@dataclass(frozen=True)
class DifficultyProfile:
    transfer_budget_multiplier: float
    board_patience: int
    starting_reputation: int
    salary_wiggle: float
    debut_transfer_budget: int
    buying_premium: float


PROFILES: dict[Difficulty, DifficultyProfile] = {
    Difficulty.RECRUIT: DifficultyProfile(1.45, 90, 62, 1.10, 2_000_000, 0.85),
    Difficulty.COACH: DifficultyProfile(1.20, 80, 56, 1.05, 1_250_000, 0.93),
    Difficulty.MANAGER: DifficultyProfile(1.00, 70, 50, 1.00, 750_000, 1.00),
    Difficulty.LEGEND: DifficultyProfile(0.80, 55, 44, 0.95, 350_000, 1.12),
}


def profile_for(difficulty: Difficulty) -> DifficultyProfile:
    return PROFILES[Difficulty(difficulty)]