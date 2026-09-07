"""Season rollover and the living football world.

At the end of a finished season the world moves on: players age and decline,
veterans retire, academies promote replacements, the board sets fresh
objectives, prize money is paid, and the next season's league and cup
calendars are generated. Everything is deterministic for the career seed.
"""

from __future__ import annotations

from manager.core.enums import FixtureStatus, NewsCategory
from manager.core.models import CareerState, NewsArticle, Player, Season
from manager.data.players import _make_player
from manager.rng import SeededRng

SQUAD_SIZE = 25
RETIRE_ODDS = {35: 0.5, 34: 0.25, 33: 0.12}


class SeasonError(Exception):
    pass


def start_next_season(state: CareerState) -> dict:
    """Roll the career into the following season once the current one is over."""
    season = state.seasons[state.current_season]
    if not season.finished:
        raise SeasonError("the current season must be finished first")
    if state.current_week < season.total_weeks:
        raise SeasonError("the season is not actually complete")
    rollover(state)
    return {"season": state.current_season, "week": state.current_week}


def rollover(state: CareerState) -> None:
    """Advance the world one season year."""
    old_season = state.seasons[state.current_season]
    new_year = old_season.end_year
    new_id, new_name = _next_season_ids(old_season)

    from manager.systems.transfers import return_loans

    return_loans(state)
    _age_and_decline(state, new_year)
    _retire(state, new_year)
    _young_growth(state, new_year)

    prize = _prize_money(state, old_season)
    _academy_intake(state, new_year, new_id)
    _record_trophies(state, old_season)
    _rebuild_finances(state, prize)

    season = Season(
        id=new_id,
        name=new_name,
        start_year=new_year,
        end_year=new_year + 1,
        total_weeks=old_season.total_weeks,
        competition_ids=list(state.competitions),
    )
    state.seasons[new_id] = season

    state.current_season = new_id
    state.current_week = 0
    state.matchday_history = []

    from manager.systems.fixtures import generate_league_fixtures

    state.fixtures = generate_league_fixtures(new_id, "apex_division", list(state.competitions["apex_division"].club_ids))
    from manager.systems.cup import setup_cup
    setup_cup(state)

    _renew_objectives(state, new_id)
    state.news.append(NewsArticle(
        id=f"news_{new_id}_w0_preseason",
        season=new_id,
        week=0,
        category=NewsCategory.MATCH_RESULT,
        headline=f"{state.user_club().name} are back for {new_id}",
        body=f"The {new_name} season begins. Good luck this year.",
        clubs_involved=[state.user_club_id],
    ))
    state.news = state.news[-80:]

    _rebuild_user_selection(state)


def _next_season_ids(season: Season) -> tuple[str, str]:
    start = season.start_year + 1
    return f"{start}-{str(start + 1)[2:]}", f"{start}/{start + 1}"


def _season_year(season_id: str) -> int:
    return int(season_id.split("-")[0])


def _age_and_decline(state: CareerState, new_year: int) -> None:
    rng = SeededRng(state.seed)
    for player in state.players.values():
        if player.retired:
            continue
        age = player.age_as_of(new_year)
        points = age - 30 if age >= 31 else 0
        if age >= 32:
            points += (age - 31) // 2
        if points <= 0:
            continue
        for _ in range(min(points, 4)):
            name = rng.choice(list(player.attributes.__dataclass_fields__), stream=f"rollover_decline_{player.id}")
            before = getattr(player.attributes, name)
            setattr(player.attributes, name, max(1, before - 1))
        player.fitness = max(40, player.fitness)
        player.energy = 100


def _young_growth(state: CareerState, new_year: int) -> None:
    """Season-to-season development: players under their potential improve year on year."""
    rng = SeededRng(state.seed)
    for player in state.players.values():
        if player.retired:
            continue
        age = player.age_as_of(new_year)
        if age > 23 or player.overall >= player.potential:
            continue
        boosts = 2 if age <= 20 else 1
        if rng.random(f"rollover_grow_{player.id}") >= 0.85:
            continue
        for _ in range(boosts):
            if player.overall >= player.potential:
                break
            name = rng.choice(list(player.attributes.__dataclass_fields__), stream=f"rollover_grow_attr_{player.id}")
            setattr(player.attributes, name, min(99, getattr(player.attributes, name) + 1))


def _retire(state: CareerState, new_year: int) -> None:
    rng = SeededRng(state.seed)
    for club in state.clubs.values():
        survivors = []
        for pid in club.squad_ids:
            player = state.players.get(pid)
            if player is None:
                continue
            age = player.age_as_of(new_year)
            odds = 0.9 if age >= 36 else RETIRE_ODDS.get(age, 0.0)
            if age >= 32 and player.overall <= 58:
                odds = max(odds, 0.45)
            if age <= 17:
                odds = 0.0
            if rng.random(f"rollover_retire_{pid}") < odds:
                player.retired = True
                player.club_id = None
                continue
            survivors.append(pid)
        club.squad_ids = survivors
    for player_id in list(state.players):
        player = state.players[player_id]
        if player.retired:
            continue
        if player.club_id is None:
            age = player.age_as_of(new_year)
            odds = 0.9 if age >= 37 else 0.3 if age >= 34 else 0.1
            if rng.random(f"rollover_retire_fa_{player_id}") < odds:
                player.retired = True


def _academy_intake(state: CareerState, new_year: int, season_id: str) -> None:
    from manager.core.models import Contract

    rng = SeededRng(state.seed ^ 0xACA0E7)
    roles = ["GK", "CB", "FB", "DM", "CM", "AM", "W", "ST"]
    for club in state.clubs.values():
        missing = SQUAD_SIZE - len(club.squad_ids)
        if missing <= 0:
            continue
        index = 0
        while index < missing:
            role = roles[(index + len(club.squad_ids)) % len(roles)]
            player_id = f"{club.id.replace('-', '_')}_youth_{index:02d}"
            while player_id in state.players:
                index += 1
                player_id = f"{club.id.replace('-', '_')}_youth_{index:02d}"
            age = rng.randint(16, 18, f"youth_age_{club.id}_{index}")
            player = _make_player(
                player_id, club.id, role, club.reputation, "prospect", new_year, rng,
                age_override=age,
            )
            wage = max(250, int(player.overall * 400))
            player.contract = Contract(
                player_id=player.id,
                club_id=club.id,
                weekly_wage=wage,
                start_season=season_id,
                end_season=season_id and f"{_season_year(season_id) + 3}-{str(_season_year(season_id) + 4)[2:]}",
            )
            state.players[player.id] = player
            club.squad_ids.append(player.id)
            index += 1


def _prize_money(state: CareerState, season: Season) -> int:
    from manager.systems.fixtures import compute_standings

    standings = compute_standings(state.fixtures)
    order = [row.club_id for row in standings]
    position = order.index(state.user_club_id) + 1 if state.user_club_id in order else 18
    return max(0, 8_000_000 - position * 330_000)


def _record_trophies(state: CareerState, season: Season) -> None:
    from manager.systems.cup import cup_champion
    from manager.systems.fixtures import compute_standings

    standings = compute_standings(state.fixtures)
    position = next(
        (i + 1 for i, row in enumerate(standings) if row.club_id == state.user_club_id),
        None,
    )
    won: list[str] = []
    if position == 1:
        won.append(state.competitions["apex_division"].trophy_name)
    if cup_champion(state) == state.user_club_id:
        won.append(state.competitions["continental_series"].trophy_name)
    if won:
        club = state.user_club()
        club.trophy_history.extend(f"{season.name} - {title}" for title in won)
        state.manager.trophy_count += len(won)


def _rebuild_finances(state: CareerState, prize: int) -> None:
    for club in state.clubs.values():
        wages = sum(
            p.contract.weekly_wage for pid in club.squad_ids
            if (p := state.players.get(pid)) is not None and p.contract
        )
        club.finances.weekly_wage_spend = wages
        club.finances.weekly_wage_budget = max(1, int(wages * 1.22))
        income = club.reputation * 90_000 + club.capacity * 380
        bonus = prize if club.id == state.user_club_id else int(income * 0.35)
        club.finances.balance += income + bonus
        club.finances.transfer_budget = club.reputation * 120_000 + int(income * 0.18)


def _renew_objectives(state: CareerState, season_id: str) -> None:
    from manager.api.objectives import build_objectives, package_for_key

    key = "steady"
    for objective in state.user_club().objectives:
        parts = objective.objective_id.split("_")
        if len(parts) >= 3:
            key = parts[-2]
            break
    package = package_for_key(key, state.difficulty)
    if package is not None:
        state.user_club().objectives = build_objectives(package, season_id, state.user_club_id)


def _rebuild_user_selection(state: CareerState) -> None:
    from manager.systems.squads import build_best_xi

    club = state.user_club()
    squad = [state.players[pid] for pid in club.squad_ids if pid in state.players]
    state.selections[club.id] = build_best_xi(club.id, squad)