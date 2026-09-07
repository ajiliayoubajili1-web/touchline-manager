"""Validation rules for game-state changes.

Every mutation of the game state in the API layer is checked before it happens.
These functions raise :class:`ValidationError` with a human-readable message so
the UI can surface the exact problem to the player.
"""

from __future__ import annotations

from manager.core.enums import Position
from manager.core.models import Club, ClubFinances, Contract, Player, SquadSelection, Tactics
from manager.core.ratings import ATTRIBUTE_NAMES

MIN_ATTRIBUTE = 1
MAX_ATTRIBUTE = 99


class ValidationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def validate_attribute_value(name: str, value: int) -> None:
    require(MIN_ATTRIBUTE <= value <= MAX_ATTRIBUTE,
            f"attribute {name} must be between {MIN_ATTRIBUTE} and {MAX_ATTRIBUTE}, got {value}")
    require(name in ATTRIBUTE_NAMES, f"unknown attribute {name!r}")


def validate_player(player: Player) -> None:
    require(bool(player.id), "player id must not be empty")
    require(bool(player.first_name) and bool(player.last_name), "player must have a name")
    require(bool(player.positions), "player must have at least one position")
    require(player.preferred_position in player.positions,
            "preferred position must be in the player's positions")
    require(1 <= player.potential <= 99, f"potential out of range: {player.potential}")
    for name in ATTRIBUTE_NAMES:
        validate_attribute_value(name, getattr(player.attributes, name))


def validate_finances(finances: ClubFinances) -> None:
    require(finances.balance >= 0, "club balance cannot be negative")
    require(finances.transfer_budget >= 0, "transfer budget cannot be negative")
    require(finances.weekly_wage_budget >= 0, "wage budget cannot be negative")
    require(finances.weekly_wage_spend <= finances.weekly_wage_budget,
            "weekly wage spend exceeds the wage budget")


def validate_tactics(tactics: Tactics) -> None:
    require(isinstance(tactics.formation, str) and tactics.formation,
            "formation must be a non-empty string")
    defenders, midfielders, forwards = parse_formation(tactics.formation)
    require(defenders + midfielders + forwards == 10,
            f"formation {tactics.formation} must select 10 outfield players")
    require(3 <= defenders <= 5, f"formation {tactics.formation} needs 3 to 5 defenders")
    require(midfielders >= 1 and forwards >= 1,
            f"formation {tactics.formation} needs at least one midfielder and one forward")


def parse_formation(formation: str) -> tuple[int, int, int]:
    """Parse a formation string like ``4-3-3`` into (defenders, mids, forwards)."""
    parts = [p for p in formation.split("-") if p.isdigit()]
    require(2 <= len(parts) <= 4, f"invalid formation {formation!r}")
    numbers = [int(p) for p in parts]
    require(all(p >= 0 for p in numbers), f"invalid formation {formation!r}")
    require(sum(numbers) == 10,
            f"formation {formation!r} must select exactly 10 outfield players")
    defenders = numbers[0]
    forwards = numbers[-1]
    midfielders = sum(numbers[1:-1])
    return defenders, midfielders, forwards


def validate_squad_selection(selection: SquadSelection, players: dict[str, Player]) -> None:
    require(len(selection.starter_ids) == 11,
            f"starting XI must contain exactly 11 players, got {len(selection.starter_ids)}")
    require(len(selection.substitute_ids) <= 5,
            f"at most 5 substitutes allowed, got {len(selection.substitute_ids)}")
    require(len(set(selection.starter_ids)) == 11, "starting XI contains duplicate players")

    selected = set(selection.starter_ids) | set(selection.substitute_ids)
    require(len(selected) == len(selection.starter_ids) + len(selection.substitute_ids),
            "a player cannot both start and sit on the bench")

    goalkeepers = 0
    for player_id in selection.starter_ids:
        require(player_id in players, f"selected player {player_id} does not exist")
        player = players[player_id]
        require(player.club_id == selection.club_id,
                f"{player.full_name} does not belong to this club")
        if player.preferred_position == Position.GK or Position.GK in player.positions:
            goalkeepers += 1
    require(goalkeepers == 1, "the starting XI must contain exactly one goalkeeper")


def validate_transfer_params(fee: int, weekly_wage: int, contract_years: int) -> None:
    require(fee >= 0, f"transfer fee cannot be negative, got {fee}")
    require(weekly_wage >= 0, f"weekly wage cannot be negative, got {weekly_wage}")
    require(1 <= contract_years <= 5, f"contract length must be 1-5 years, got {contract_years}")


def validate_transfer_affordability(club: Club, fee: int, weekly_wage: int) -> None:
    validate_finances(club.finances)
    require(fee <= club.finances.transfer_budget,
            f"fee {fee} exceeds transfer budget {club.finances.transfer_budget}")
    require(weekly_wage <= club.finances.weekly_wage_budget - club.finances.weekly_wage_spend,
            "weekly wage exceeds the remaining wage budget")


def validate_contract(contract: Contract, players: dict[str, Player]) -> None:
    require(contract.start_season <= contract.end_season,
            "contract end must not precede its start")
    require(contract.player_id in players, "contract references an unknown player")
    require(contract.weekly_wage >= 0, "contract wage cannot be negative")