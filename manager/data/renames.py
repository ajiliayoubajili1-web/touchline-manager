"""Editable custom names.

Players and clubs can be renamed through a JSON file (by default
``custom_names.json`` at the project root). This is a cosmetic, data-driven
override: the underlying database stays original and untouched, and renaming
never affects the seeded random generation.

File schema::

    {
      "_doc": "optional instructions (keys starting with _ are ignored)",
      "clubs":   { "clb_northbay": "BARCA" },
      "players": { "clb_northbay_03": "MISSI" }
    }

Player values may be a full name string, or an object with ``first_name`` /
``last_name``. Keys that do not match any club or player produce a warning and
are ignored. Unknown player/club references do not raise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from manager.core.enums import Position
from manager.core.ratings import ATTRIBUTE_NAMES, overall_rating
from manager.core.validate import clamp

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_NAMES_FILE = PROJECT_ROOT / "custom_names.json"


@dataclass
class NameOverrides:
    clubs: dict[str, str] = field(default_factory=dict)
    players: dict[str, str | dict] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.clubs and not self.players


def load_custom_names(path: str | Path | None = None) -> NameOverrides:
    """Load and validate the optional custom-names file."""
    overrides = NameOverrides()
    target = Path(path) if path else DEFAULT_NAMES_FILE
    if not target.is_file():
        return overrides

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        overrides.warnings.append(f"could not read custom names file {target}: {exc}")
        return overrides

    if not isinstance(data, dict):
        overrides.warnings.append(f"custom names file {target} must contain a JSON object")
        return overrides

    for key in ("clubs", "players"):
        section = data.get(key, {})
        if not isinstance(section, dict):
            overrides.warnings.append(f"'{key}' section in {target} must be an object")
            continue
        for entry_key, value in section.items():
            if entry_key.startswith("_"):
                continue
            if not isinstance(value, (str, dict)):
                overrides.warnings.append(
                    f"ignoring {key} entry {entry_key!r}: value must be a string or object")
                continue
            if key == "players" and isinstance(value, dict):
                if all(not value.get(k) for k in ("first_name", "last_name", "age", "rating", "position")):
                    overrides.warnings.append(
                        f"ignoring player {entry_key!r}: name object is empty")
                    continue
            (overrides.clubs if key == "clubs" else overrides.players)[entry_key] = value

    return overrides


def apply_custom_names(world, overrides: NameOverrides) -> list[str]:
    """Apply name overrides to a generated world. Returns warnings."""
    warnings = list(overrides.warnings)

    if overrides.clubs:
        club_by_id = {club.id: club for club in world.clubs}
        for key, new_name in overrides.clubs.items():
            resolved = _resolve_club_key(world, club_by_id, key)
            if resolved is None:
                warnings.append(f"custom club name {key!r} does not match any club")
                continue
            resolved.name = new_name

    if overrides.players:
        player_by_id = {player.id: player for player in world.players}
        for key, alias in overrides.players.items():
            resolved = _resolve_player_key(world, player_by_id, key)
            if resolved is None:
                warnings.append(f"custom player name {key!r} does not match any player")
                continue
            if isinstance(alias, str):
                resolved.first_name = alias
                resolved.last_name = ""
            else:
                resolved.first_name = alias.get("first_name", resolved.first_name)
                resolved.last_name = alias.get("last_name", resolved.last_name)
                if alias.get("age") is not None:
                    try:
                        new_age = int(alias["age"])
                    except (TypeError, ValueError):
                        warnings.append(f"invalid age for player {resolved.id!r}: {alias['age']!r}")
                    else:
                        _set_age(resolved, new_age)
                if alias.get("position") is not None:
                    try:
                        new_position = Position(alias["position"])
                    except (TypeError, ValueError):
                        warnings.append(f"invalid position for player {resolved.id!r}: {alias['position']!r}")
                    else:
                        _set_position(resolved, new_position)
                if alias.get("rating") is not None:
                    try:
                        new_rating = int(alias["rating"])
                    except (TypeError, ValueError):
                        warnings.append(f"invalid rating for player {resolved.id!r}: {alias['rating']!r}")
                    else:
                        _set_rating(resolved, new_rating)

    return warnings


def _set_age(player, age: int) -> None:
    """Shift a player's date of birth so they are ``age`` years old."""
    from datetime import date

    season_year = getattr(player, "_season_start_year", None)
    today = date.today()
    current_age = _current_age(player.date_of_birth, today)
    delta = current_age - age
    try:
        player.date_of_birth = date(
            player.date_of_birth.year + delta,
            player.date_of_birth.month,
            player.date_of_birth.day,
        )
    except ValueError:
        player.date_of_birth = date(player.date_of_birth.year + delta, 6, 15)


def _current_age(dob, today) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _set_position(player, position: Position) -> None:
    """Set a player's primary and occupied positions."""
    player.preferred_position = position
    if position not in player.positions:
        player.positions = [position] + [p for p in player.positions if p != position]


def _set_rating(player, target: int) -> None:
    """Scale a player's attributes so their overall rating becomes ``target``.

    Uses a proportional adjustment toward the target so the position-weighted
    overall lands on (or as close as possible to) ``target``.
    """
    target = clamp(target, 1, 99)
    for _ in range(60):
        current = overall_rating(player.attributes, player.preferred_position)
        diff = target - current
        if diff == 0:
            break
        step = 1 if diff > 0 else -1
        made_change = False
        for name in ATTRIBUTE_NAMES:
            old = getattr(player.attributes, name)
            new = clamp(old + step, 1, 99)
            if new != old:
                setattr(player.attributes, name, new)
                made_change = True
        if not made_change:
            break


def _resolve_club_key(world, club_by_id: dict[str, object], key: str):
    if key in club_by_id:
        return club_by_id[key]
    slug = key.removeprefix("clb_")
    for club in world.clubs:
        if club.id.replace("clb_", "") == slug:
            return club
    return None


def _resolve_player_key(world, player_by_id: dict[str, object], key: str):
    if key in player_by_id:
        return player_by_id[key]
    if "." in key:
        club_slug, index = key.split(".", 1)
        candidate = f"clb_{club_slug}_{index}"
        if candidate in player_by_id:
            return player_by_id[candidate]
    for player in world.players:
        if player.id == key.replace(".", "_"):
            return player
    return None