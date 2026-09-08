"""Continental Cup — a Champions-style knockout for the title.

A 16-team single-elimination tournament layered on top of the league season.
Qualification is by club reputation (top 15 of the Apex Division plus the
player's club, so a minnow manager always has continental nights). Rounds run on
fixed weeks around the league calendar; a draw is settled by a penalty shootout,
and the final winner lifts the Continental Cup.
"""

from __future__ import annotations

from manager.core.enums import FixtureStatus, NewsCategory
from manager.core.models import CareerState, Competition, CompetitionType, Fixture, NewsArticle
from manager.rng import SeededRng
from manager.systems.fixtures import matchday_date
from manager.systems.match import apply_match_results, simulate_match

CUP_ID = "continental_series"


def _year_of(season_id: str) -> int:
    try:
        return int(season_id.split("-")[0])
    except (ValueError, IndexError):
        return 2026
ROUND_ROUTING = {
    "round_of_16": (2, "quarter_final"),
    "quarter_final": (8, "semi_final"),
    "semi_final": (19, "final"),
    "final": (30, None),
}
ROUND_NAMES = {
    "round_of_16": "Round of 16",
    "quarter_final": "Quarter-final",
    "semi_final": "Semi-final",
    "final": "Final",
}


def setup_cup(state: CareerState) -> None:
    """Register the continental competition and generate the Round of 16 (seeded)."""
    season = state.seasons[state.current_season]
    if CUP_ID not in state.competitions:
        apex = state.competitions["apex_division"]
        state.competitions[CUP_ID] = Competition(
            id=CUP_ID,
            name="Continental Cup",
            comp_type=CompetitionType.CUP,
            nation="International",
            tier=1,
            club_ids=list(apex.club_ids),
            params={"rounds": list(ROUND_ROUTING.keys()), "teams": 16, "legs": 1},
            trophy_name="Continental Cup",
        )
    if CUP_ID not in season.competition_ids:
        season.competition_ids.append(CUP_ID)

    existing = [f for f in state.fixtures if f.competition_id == CUP_ID and f.season == state.current_season]
    if existing:
        return

    qualified = _qualifiers(state)
    text = _round_caption("round_of_16", len(qualified) // 2)
    for index in range(0, len(qualified), 2):
        home, away = qualified[index], qualified[index + 1]
        cupholder = state.clubs[home]
        state.fixtures.append(Fixture(
            id=_cup_id(state, "r16", index // 2),
            season=state.current_season,
            competition_id=CUP_ID,
            week=ROUND_ROUTING["round_of_16"][0],
            home_club_id=home,
            away_club_id=away,
            round="round_of_16",
            date=matchday_date(_year_of(state.current_season), ROUND_ROUTING["round_of_16"][0], CUP_ID),
            attendance=cupholder.capacity,
        ))
    state.news.append(NewsArticle(
        id=f"news_{state.current_season}_w0_cup_draw",
        season=state.current_season,
        week=0,
        category=NewsCategory.MATCH_RESULT,
        headline=text,
        body="The field of 16 for the Continental Cup is set.",
        clubs_involved=[c for c in qualified],
    ))


def simulate_cup_week(state: CareerState, week: int) -> None:
    """Simulate any continental ties scheduled for this week and roll round forward."""
    gameweek = [
        f for f in state.fixtures
        if f.season == state.current_season
        and f.competition_id == CUP_ID
        and f.week == week
        and f.status is FixtureStatus.SCHEDULED
    ]
    if not gameweek:
        _ensure_cup_round(state, week)
        return

    for fixture in sorted(gameweek, key=lambda f: f.id):
        is_user = fixture.home_club_id == state.user_club_id or fixture.away_club_id == state.user_club_id
        simulate_match(state, fixture, is_user=is_user)
        apply_match_results(state, fixture)
        _decide_winner(state, fixture)
        if is_user:
            _cup_advance_news(state, fixture)

    _ensure_cup_round(state, week)


def _decide_winner(state: CareerState, fixture: Fixture) -> None:
    home_goals, away_goals = fixture.home_goals, fixture.away_goals
    if home_goals == away_goals:
        rng = SeededRng(state.seed)
        home = rng.randint(0, 5, f"match_{fixture.id}_pens_home")
        away = rng.randint(0, 5, f"match_{fixture.id}_pens_away")
        while home == away:
            away = rng.randint(0, 5, f"match_{fixture.id}_pens_away")
        fixture.resolved_by = "penalties"
        fixture.winner_id = fixture.home_club_id if home > away else fixture.away_club_id
    else:
        fixture.winner_id = fixture.home_club_id if home_goals > away_goals else fixture.away_club_id


def _ensure_cup_round(state: CareerState, after_week: int) -> None:
    """Materialize the next round from the winners of the round that just finished."""
    played_round = next(
        (key for key, (w, _) in ROUND_ROUTING.items() if w == after_week and key != "final"),
        None,
    )
    if played_round is None:
        return
    fixtures = [f for f in state.fixtures
                if f.season == state.current_season and f.competition_id == CUP_ID and f.round == played_round]
    if not fixtures or any(f.status is not FixtureStatus.PLAYED for f in fixtures):
        return

    next_round = ROUND_ROUTING[played_round][1]
    if next_round is None:
        return
    week = ROUND_ROUTING[next_round][0]

    existing = [f for f in state.fixtures
                if f.season == state.current_season and f.competition_id == CUP_ID and f.round == next_round]
    if existing:
        return

    ordered = sorted(fixtures, key=lambda f: f.id)
    winners = [f.winner_id for f in ordered if f.winner_id]
    for index in range(0, len(winners), 2):
        home, away = winners[index], winners[index + 1]
        cupholder = state.clubs[home]
        state.fixtures.append(Fixture(
            id=_cup_id(state, _round_slug(next_round), index // 2),
            season=state.current_season,
            competition_id=CUP_ID,
            week=week,
            home_club_id=home,
            away_club_id=away,
            round=next_round,
            date=matchday_date(_year_of(state.current_season), week, CUP_ID),
            attendance=cupholder.capacity,
        ))


def cup_champion(state: CareerState) -> str | None:
    finals = [
        f for f in state.fixtures
        if f.season == state.current_season and f.competition_id == CUP_ID and f.round == "final"
    ]
    return finals[0].winner_id if finals and finals[0].winner_id else None


def _qualifiers(state: CareerState) -> list[str]:
    """Top 15 Apex clubs by reputation, plus the manager's club, drawn into a seeded order."""
    clubs = sorted(
        (c for c in state.clubs.values() if c.id in state.competitions["apex_division"].club_ids),
        key=lambda c: (-c.reputation, c.name),
    )
    field = [c.id for c in clubs if c.id != state.user_club_id][:15]
    if state.user_club_id not in field:
        field.append(state.user_club_id)
    rng = SeededRng(state.seed)
    order = []
    for pos, club_id in enumerate(field):
        order.append((rng.random(f"cup_qual_{pos}"), club_id))
    order.sort()
    return [club_id for _, club_id in order]


def _cup_advance_news(state: CareerState, fixture: Fixture) -> None:
    club = state.user_club()
    if fixture.round == "final":
        headline = f"{club.name} win the Continental Cup!"
        body = f"{club.name} lift the trophy after beating {state.club(_opponent(state, fixture)).name}."
    else:
        headline = (
            f"{club.name} reach the {ROUND_NAMES.get(_next_round_name(fixture.round), 'next round')} of the Continental Cup"
        )
        body = f"{club.name} advance past {state.club(_opponent(state, fixture)).name}."
    state.news.append(NewsArticle(
        id=f"news_{state.current_season}_w{fixture.week}_{fixture.id}",
        season=state.current_season,
        week=fixture.week,
        category=NewsCategory.MATCH_RESULT,
        headline=headline,
        body=body,
        clubs_involved=[fixture.home_club_id, fixture.away_club_id],
    ))


def _opponent(state, fixture) -> str:
    return fixture.home_club_id if fixture.away_club_id == state.user_club_id else fixture.away_club_id


def _next_round_name(round_key: str) -> str:
    return ROUND_NAMES.get(ROUND_ROUTING.get(round_key, ("", None))[1], "")


def _round_caption(round_key: str, ties: int) -> str:
    prefix = {"round_of_16": "Continental Cup: Round of 16 draw",
              "quarter_final": "Quarter-finals",
              "semi_final": "Semi-finals",
              "final": "Final"}[round_key]
    return f"{prefix} set ({ties} ties)"


def _round_slug(round_key: str) -> str:
    return {"quarter_final": "qf", "semi_final": "sf", "final": "f"}[round_key]


def _cup_id(state: CareerState, slug: str, index: int) -> str:
    return f"fix_{state.current_season}_{CUP_ID}_{slug}_{index:02d}"