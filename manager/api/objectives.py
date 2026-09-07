"""Career objective packages.

At career creation the manager picks one package; it becomes the board's
objectives for the first season. Packages are data, so new ones can be added
without touching the UI or the career logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from manager.core.enums import Difficulty
from manager.core.models import ClubObjective


@dataclass
class ObjectivePackage:
    key: str
    label: str
    description: str
    objectives: list[dict] = field(default_factory=list)
    reward_bonus: int = 0


def packages_for(difficulty: Difficulty) -> list[ObjectivePackage]:
    """Return the objective packages offered at career creation."""
    bonus = _reward_bonus(difficulty)
    return [
        ObjectivePackage(
            key="steady",
            label="Steady & Solvent",
            description="Keep the club competitive and the books healthy.",
            reward_bonus=bonus,
            objectives=[
                {"type": "league_position", "finish_at_most": 12, "label": "Finish inside the top 12"},
                {"type": "finances_positive", "label": "End the season with a positive balance"},
            ],
        ),
        ObjectivePackage(
            key="trophy",
            label="Chasing Silverware",
            description="Push for the top and a cup run.",
            reward_bonus=bonus * 2,
            objectives=[
                {"type": "league_position", "finish_at_most": 3, "label": "Finish inside the top 3"},
                {"type": "cup_round", "round": 2, "label": "Reach the Presidents' Cup semi-final"},
            ],
        ),
        ObjectivePackage(
            key="youth",
            label="Homegrown",
            description="Give the academy's young players a real chance.",
            reward_bonus=bonus,
            objectives=[
                {"type": "youth_minutes", "minutes": 2000, "label": "Give young players 2,000 league minutes"},
                {"type": "league_position", "finish_at_most": 9, "label": "Still finish inside the top 9"},
            ],
        ),
    ]


def package_for_key(key: str, difficulty: Difficulty) -> ObjectivePackage | None:
    for package in packages_for(difficulty):
        if package.key == key:
            return package
    return None


def build_objectives(package: ObjectivePackage, season: str, club_id: str) -> list[ClubObjective]:
    objectives = []
    for index, spec in enumerate(package.objectives):
        target = dict(spec)
        target.pop("label", None)
        label = spec.get("label", target.get("type", "objective"))
        objectives.append(
            ClubObjective(
                objective_id=f"obj_{club_id}_{package.key}_{index}",
                label=label,
                target=target,
                reward=package.reward_bonus,
                season=season,
            )
        )
    return objectives


def _reward_bonus(difficulty: Difficulty) -> int:
    return {
        Difficulty.RECRUIT: 400_000,
        Difficulty.COACH: 300_000,
        Difficulty.MANAGER: 250_000,
        Difficulty.LEGEND: 200_000,
    }[Difficulty(difficulty)]