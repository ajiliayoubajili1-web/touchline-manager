"""Player training plans and weekly development (Phase 5).

Each player has an individual plan: a training focus (which attributes get the
attention), a training intensity (low/normal/high), a tactical role allowed by
their position, and a general duty (defend/support/attack). Plans are the
manager's levers: ratings grow deterministically each week for the whole world,
and user-squad development is recorded in the player's history.
"""

from __future__ import annotations

from manager.core.enums import (
    Position,
    TacticalDuty,
    TrainingFocus,
    TrainingIntensity,
)
from manager.core.models import CareerState, DevelopmentRecord, Player
from manager.core.validate import require
from manager.rng import SeededRng

DUTIES = [str(d) for d in TacticalDuty]
FOCUSES = [str(f) for f in TrainingFocus]
INTENSITIES = [str(i) for i in TrainingIntensity]

FOCUS_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "general": ("pace", "shooting", "passing", "dribbling", "defending", "physical", "goalkeeper"),
    "attacking": ("shooting", "dribbling"),
    "defending": ("defending", "physical"),
    "technical": ("passing", "dribbling"),
    "physical": ("pace", "physical"),
    "goalkeeping": ("goalkeeper",),
}

POSITION_GROUP = {
    Position.GK: "gk",
    Position.LB: "def", Position.CB: "def", Position.RB: "def", Position.WB: "def",
    Position.DM: "mid", Position.CM: "mid", Position.AM: "mid",
    Position.LM: "wide", Position.RM: "wide", Position.LW: "wide", Position.RW: "wide",
    Position.CF: "att", Position.ST: "att",
}

ROLES: dict[str, list[str]] = {
    "gk": ["standard", "shot_stopper", "sweeper_keeper"],
    "def": ["standard", "ball_playing", "no_holds_barred", "inverted"],
    "mid": ["standard", "anchor", "playmaker", "box_to_box"],
    "wide": ["standard", "winger", "inverted", "wide_playmaker"],
    "att": ["standard", "poacher", "target_man", "supporting_forward"],
}

DEFAULT_ROLE = "standard"


def allowed_roles(player: Player) -> list[str]:
    return ROLES.get(POSITION_GROUP.get(player.preferred_position, "mid"), ROLES["mid"])


def _normalize(value: str) -> str:
    return str(value or "").strip().lower()


def apply_training_plan(
    state: CareerState,
    player_id: str,
    focus: str,
    intensity: str,
    role: str,
    duty: str,
) -> Player:
    """Validate and write a player's training plan + tactical role (user squad)."""
    player = state.players.get(player_id)
    require(player is not None, f"unknown player {player_id!r}")
    require(player.club_id == state.user_club_id,
            "training plans can only be set for players in your squad")

    focus = _normalize(focus) or str(TrainingFocus.GENERAL)
    intensity = _normalize(intensity) or str(TrainingIntensity.NORMAL)
    role = _normalize(role) or DEFAULT_ROLE
    duty = _normalize(duty) or str(TacticalDuty.SUPPORT)

    require(focus in FOCUS_ATTRIBUTES, f"unknown training focus {focus!r}")
    require(intensity in INTENSITIES, f"unknown training intensity {intensity!r}")
    require(role in allowed_roles(player), f"{role!r} is not a valid role for {player.full_name}")
    require(duty in DUTIES, f"unknown duty {duty!r}")

    player.training_focus = TrainingFocus(focus)
    player.training_intensity = TrainingIntensity(intensity)
    player.tactical_role = role
    player.tactical_duty = TacticalDuty(duty)
    return player


def development_tick(state: CareerState, week: int) -> None:
    """Advance player development one week for the whole world, deterministically."""
    rng = SeededRng(state.seed)

    for player in state.players.values():
        if player.club_id is None or player.club_id not in state.clubs:
            continue
        before = player.overall
        growth = _growth_for_player(player, state, rng, week)
        if not growth:
            continue
        user_squad = player.club_id == state.user_club_id
        if user_squad:
            player.development_history.append(DevelopmentRecord(
                season=state.current_season,
                applied_at=f"w{week}",
                attribute_growth=growth,
                overall_before=before,
                overall_after=player.overall,
                note=_growth_note(growth),
            ))
            player.development_history = player.development_history[-16:]
            player.morale = min(100, player.morale + 2)


def _growth_for_player(player: Player, state: CareerState, rng: SeededRng, week: int) -> dict[str, int]:
    age = player.age_as_of(_season_year(state.current_season))
    if age < 16:
        factor = 1.2
    elif age <= 21:
        factor = 1.0
    elif age <= 25:
        factor = 0.55
    elif age <= 29:
        factor = 0.18
    else:
        return {}

    intensity = {"low": 0.5, "normal": 1.0, "high": 1.7}[str(player.training_intensity)]
    growth = {}
    attributes = FOCUS_ATTRIBUTES[str(player.training_focus)]
    for name in attributes:
        room = 99 - getattr(player.attributes, name)
        if room <= 0:
            continue
        prob = (room / 99.0) * (player.potential / 100.0) * factor * intensity * 0.22
        if rng.random(f"dev_{player.id}_w{week}_{name}") < prob:
            gain = 1
            if rng.random(f"dev_{player.id}_w{week}_{name}_boost") < 0.25:
                gain = 2
            growth[name] = gain
            setattr(player.attributes, name, min(99, getattr(player.attributes, name) + gain))

    if growth and str(player.training_intensity) == "high":
        player.energy = max(0, player.energy - 6)
    if growth and str(player.training_intensity) == "low":
        player.energy = min(100, player.energy + 6)
    return growth


def _growth_note(growth: dict[str, int]) -> str:
    if not growth:
        return ""
    parts = [f"{name} +{gain}" for name, gain in sorted(growth.items())]
    return "Improved " + ", ".join(parts)


def _season_year(season_id: str) -> int:
    return int(season_id.split("-")[0])