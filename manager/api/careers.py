"""Career creation.

Turns a generated world into a playable career: the user manager joins a club,
difficulty shapes the starting conditions, an objective package is set, and the
first season is opened.
"""

from __future__ import annotations

from datetime import datetime, timezone

from manager.core.enums import Difficulty
from manager.core.models import CareerState, Manager, Season, Tactics
from manager.data.renames import DEFAULT_NAMES_FILE
from manager.data.world import build_world
from manager.api.objectives import build_objectives, package_for_key
from manager.rng import SeededRng
from manager.save.files import read_save, write_save
from manager.systems.balance import profile_for
from manager.systems.squads import build_best_xi

DB_VERSION = 1


class CareerError(Exception):
    pass


def new_career(
    *,
    first_name: str,
    last_name: str,
    nationality: str,
    club_id: str,
    difficulty: str,
    objective_key: str,
    seed: int,
    favourite_coach: str = "",
    season_id: str = "2026-27",
    season_year: int = 2026,
    names_file=DEFAULT_NAMES_FILE,
) -> CareerState:
    """Create a new career and return the initial game state (not yet saved)."""
    first_name = first_name.strip()
    last_name = last_name.strip()
    if not first_name or not last_name:
        raise CareerError("manager name cannot be empty")

    try:
        difficulty_enum = Difficulty(difficulty)
    except ValueError:
        raise CareerError(f"unknown difficulty {difficulty!r}")

    package = package_for_key(objective_key, difficulty_enum)
    if package is None:
        raise CareerError(f"unknown objective package {objective_key!r}")

    world = build_world(seed=seed, season_id=season_id, season_year=season_year, names_file=names_file)
    clubs = {club.id: club for club in world.clubs}
    if club_id not in clubs:
        raise CareerError(f"unknown club {club_id!r}")

    profile = profile_for(difficulty_enum)

    rng = SeededRng(seed ^ 0xC0FFEE)
    career_id = f"career_{rng.randint(10000, 99999, 'career_id')}"

    player_map = {p.id: p for p in world.players}
    club = clubs[club_id]

    from manager.data.coaches import coach_by_key, coach_tactics

    coach = coach_by_key(favourite_coach)
    coach_tactics_profile = coach_tactics(favourite_coach) if coach else None
    if coach_tactics_profile is not None:
        club.tactics = coach_tactics_profile

    club.finances.transfer_budget = int(club.finances.transfer_budget * profile.transfer_budget_multiplier)
    club.finances.transfer_budget += profile.debut_transfer_budget
    club.finances.weekly_wage_budget = int(club.finances.weekly_wage_budget * profile.salary_wiggle)

    manager = Manager(
        id=f"mgr_{career_id}",
        first_name=first_name,
        last_name=last_name,
        nationality=nationality,
        age=44,
        reputation=profile.starting_reputation,
        tactics=Tactics(formation=club.tactics.formation),
        club_id=club_id,
        is_user=True,
        contract_end_season=f"{season_year + 2}-{str(season_year + 3)[2:]}",
        favourite_coach=favourite_coach if coach else "",
    )
    club.manager_id = manager.id

    objectives = build_objectives(package, season_id, club_id)
    club.objectives = objectives

    state = CareerState(
        version=DB_VERSION,
        career_id=career_id,
        manager_name=manager.full_name,
        difficulty=difficulty_enum,
        seed=seed,
        user_club_id=club_id,
        current_season=season_id,
        current_week=0,
        manager=manager,
        title=_career_title(club.name, season_id),
        created_at=_now(),
    )
    state.clubs.update(clubs)
    state.players.update(player_map)
    state.competitions.update({c.id: c for c in world.competitions})

    apex = next(c for c in world.competitions if c.id == "apex_division")
    season = Season(
        id=season_id,
        name=f"{season_year}/{season_year + 1}",
        start_year=season_year,
        end_year=season_year + 1,
        total_weeks=max(apex.params["rounds"], 34),
        competition_ids=[c.id for c in world.competitions],
    )
    state.seasons[season_id] = season

    apex = next(c for c in world.competitions if c.id == "apex_division")
    from manager.systems.fixtures import generate_league_fixtures

    state.fixtures = generate_league_fixtures(season_id, "apex_division", list(apex.club_ids))

    from manager.systems.cup import setup_cup
    setup_cup(state)

    squad = [p for p in world.players if p.club_id == club_id]
    selection = build_best_xi(club_id, squad)
    state.selections[club_id] = selection

    return state


def save_new_career(state: CareerState, save_dir=None) -> CareerState:
    """Persist a freshly created career so it can be continued after restart."""
    write_save(state, save_dir)
    return state


def continue_career(career_id: str, save_dir=None):
    """Load a saved career."""
    from manager.save.files import SaveError

    if not career_id:
        raise CareerError("no career id provided")
    try:
        return read_save(career_id, save_dir)
    except SaveError as exc:
        raise CareerError(str(exc)) from exc


def _career_title(club_name: str, season_id: str) -> str:
    return f"{club_name} - {season_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")