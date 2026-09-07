"""Team-sheet logic: picking a starting XI and bench for a formation."""

from __future__ import annotations

from manager.core.enums import Position
from manager.core.models import Player, SquadSelection
from manager.core.validate import ValidationError, parse_formation

BANDS = {
    "GK": {Position.GK},
    "DF": {Position.LB, Position.CB, Position.RB, Position.WB},
    "MF": {Position.DM, Position.CM, Position.AM, Position.LM, Position.RM},
    "FW": {Position.LW, Position.RW, Position.CF, Position.ST},
}


def position_band(position: Position) -> str:
    for band, positions in BANDS.items():
        if position in positions:
            return band
    raise ValueError(f"unexpected position {position}")


def _squad_of(club_id: str, players: list[Player]) -> list[Player]:
    return [p for p in players if p.club_id == club_id]


def _rating_key(player: Player) -> tuple[int, str]:
    return (player.overall, player.id)


def build_best_xi(
    club_id: str,
    players: list[Player],
    formation: str = "4-3-3",
    available_only: bool = False,
    max_substitutes: int = 5,
) -> SquadSelection:
    """Build the strongest legal team sheet for a club given a formation.

    ``available_only`` excludes injured/suspended players so game-day lineups
    can be generated from the fit portion of the squad.
    """
    try:
        defenders, midfielders, forwards = parse_formation(formation)
    except ValidationError:
        return SquadSelection(club_id=club_id, formation="4-3-3")

    squad = _squad_of(club_id, players)
    if available_only:
        squad = [
            p for p in squad
            if (p.injury is None or p.injury.weeks_remaining == 0)
            and (p.suspension is None or p.suspension.matches_remaining == 0)
        ]

    by_band: dict[str, list[Player]] = {"GK": [], "DF": [], "MF": [], "FW": []}
    for player in squad:
        band = position_band(player.preferred_position)
        by_band[band].append(player)
    for band in by_band:
        by_band[band].sort(key=_rating_key, reverse=True)

    counts = {"GK": 1, "DF": defenders, "MF": midfielders, "FW": forwards}
    starters = []

    for band in ("GK", "DF", "MF", "FW"):
        needed = counts[band]
        picks = by_band[band][:needed]
        starters.extend(picks)

    starters = _finalize_band_fill(starters, squad, counts)

    starter_ids = [p.id for p in starters]
    picked = {p.id for p in starters}

    bench = [
        p for p in sorted(squad, key=_rating_key, reverse=True)
        if p.id not in picked
    ]
    bench = bench[:max_substitutes]

    return SquadSelection(
        club_id=club_id,
        formation=formation,
        starter_ids=starter_ids,
        substitute_ids=[p.id for p in bench],
        captain_id=starter_ids[0] if starter_ids else None,
    )


def _finalize_band_fill(starters: list[Player], squad: list[Player], counts: dict[str, int]) -> list[Player]:
    """Ensure exact slot counts, filling gaps from the best remaining players."""
    by_band: dict[str, list[Player]] = {"GK": [], "DF": [], "MF": [], "FW": []}
    for player in squad:
        by_band[position_band(player.preferred_position)].append(player)

    result: list[Player] = []
    used = set()
    for band in ("GK", "DF", "MF", "FW"):
        picks = [p for p in sorted(by_band[band], key=_rating_key, reverse=True)]
        added = 0
        for player in picks:
            if added >= counts[band]:
                break
            if player.id in used:
                continue
            result.append(player)
            used.add(player.id)
            added += 1
        shortfall = counts[band] - added
        if shortfall > 0:
            fillers = [
                p for p in sorted(squad, key=_rating_key, reverse=True)
                if p.id not in used
            ]
            for player in fillers[:shortfall]:
                result.append(player)
                used.add(player.id)
    return result