"""League fixture calendar generation.

Produces a balanced double round-robin schedule: every club plays every other
club home and away exactly once, never facing the same opponent before the
first leg is complete. Generation is pure and deterministic given the club
order, so a career's calendar never changes between saves. Each match day is
stamped with a real date — league weekends kick off on Saturdays from early
August, and cup ties are played on the midweek, FC-style.
"""

from __future__ import annotations

from datetime import date, timedelta

from manager.core.enums import FixtureStatus
from manager.core.models import Fixture, Standings

LEAGUE_ID = "apex_division"


def matchday_date(season_year: int, week: int, competition_id: str = LEAGUE_ID) -> str:
    """ISO date for a week's kickoff.

    The season opens on the first Saturday on or after 1 August; league games
    land on that Saturday, cup ties midweek (the Wednesday before).
    """
    aug_first = date(season_year, 8, 1)
    first_saturday = aug_first + timedelta(days=(5 - aug_first.weekday()) % 7)
    kickoff = first_saturday + timedelta(days=(max(1, week) - 1) * 7)
    if competition_id != LEAGUE_ID:
        kickoff -= timedelta(days=3)
    return kickoff.isoformat()


def _season_year_of(season_id: str) -> int:
    try:
        return int(season_id.split("-")[0])
    except (ValueError, IndexError):
        return 2026


def round_robin_rounds(club_ids: list[str]) -> list[list[tuple[str, str]]]:
    """Return first-leg rounds of (home, away) pairs using the circle method."""
    n = len(club_ids)
    if n < 2:
        return []
    if n % 2 != 0:
        raise ValueError("round robin requires an even number of clubs")

    fixed = club_ids[0]
    rotating = club_ids[1:]
    mid = n // 2
    rounds = []
    for r in range(n - 1):
        rot = rotating[-r:] + rotating[:-r]
        teams = [fixed] + rot
        pairs = []
        for i in range(mid):
            home = teams[i]
            away = teams[n - 1 - i]
            if i % 2 == 1:
                home, away = away, home
            pairs.append((home, away))
        rounds.append(pairs)
    return rounds


def generate_league_fixtures(
    season_id: str,
    competition_id: str,
    club_ids: list[str],
) -> list[Fixture]:
    """Generate the full double round-robin calendar for a league season."""
    first_leg = round_robin_rounds(club_ids)
    if not first_leg:
        return []
    n_rounds = len(first_leg)
    season_year = _season_year_of(season_id)

    fixtures: list[Fixture] = []
    num = 0

    for week, pairs in enumerate(first_leg, start=1):
        for home, away in pairs:
            fixtures.append(
                _fixture(season_id, competition_id, week, home, away, num,
                         matchday_date(season_year, week, competition_id))
            )
            num += 1

    for week, pairs in enumerate(reversed(first_leg), start=n_rounds + 1):
        for home, away in pairs:
            fixtures.append(
                _fixture(season_id, competition_id, week, away, home, num,
                         matchday_date(season_year, week, competition_id))
            )
            num += 1

    return fixtures


def _fixture(season_id: str, competition_id: str, week: int,
             home: str, away: str, num: int, fixture_date: str = "") -> Fixture:
    return Fixture(
        id=f"fix_{season_id}_{competition_id}_w{week:02d}_{num:03d}",
        season=season_id,
        competition_id=competition_id,
        week=week,
        home_club_id=home,
        away_club_id=away,
        status=FixtureStatus.SCHEDULED,
        date=fixture_date,
    )


def compute_standings(fixtures: list[Fixture]) -> list[Standings]:
    """Derive the league table purely from played league fixtures."""
    rows: dict[str, Standings] = {}

    for fixture in fixtures:
        if fixture.score is None or fixture.competition_id != LEAGUE_ID:
            continue
        home = rows.setdefault(fixture.home_club_id, Standings(club_id=fixture.home_club_id))
        away = rows.setdefault(fixture.away_club_id, Standings(club_id=fixture.away_club_id))
        gh, ga = fixture.score
        home.played += 1
        away.played += 1
        home.goals_for += gh
        home.goals_against += ga
        away.goals_for += ga
        away.goals_against += gh
        if gh > ga:
            home.won += 1
            away.lost += 1
            home.points += 3
        elif gh == ga:
            home.drawn += 1
            away.drawn += 1
            home.points += 1
            away.points += 1
        else:
            away.won += 1
            home.lost += 1
            away.points += 3

    ordered = sorted(
        rows.values(),
        key=lambda r: (-r.points, -r.goal_difference, -r.goals_for, r.club_id),
    )
    return ordered