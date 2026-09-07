"""Editorial news desk (Phase 7).

After every matchweek the desk writes the story of the campaign: result
round-ups, the upset of the week, the scoring races, club streaks and the
shape of the table. When the season ends it hands out the Golden Boot, the
Player of the Season and the Young Player of the Season awards. Everything is
seeded from the career seed, so identical careers read the same back pages.

Articles live in ``state.news`` (already persisted by the save system); this
module only owns their generation and a canonical ``add_news`` helper so every
writer follows the same id scheme and cap.
"""

from __future__ import annotations

from manager.core.enums import NewsCategory
from manager.core.models import CareerState, NewsArticle, Player
from manager.rng import SeededRng

from manager.systems.fixtures import LEAGUE_ID, compute_standings

NEWS_CAP = 200


def add_news(
    state: CareerState,
    category: NewsCategory,
    headline: str,
    body: str,
    clubs: list[str] | None = None,
    players: list[str] | None = None,
) -> NewsArticle:
    """Append one article under the desk's id scheme and keep the feed bounded."""
    counter = len(state.news) + 1
    article = NewsArticle(
        id=f"news_{state.current_season}_desk_w{state.current_week}_{counter:03d}",
        season=state.current_season,
        week=state.current_week,
        category=category,
        headline=headline,
        body=body,
        clubs_involved=[c for c in (clubs or []) if c],
        players_involved=list(players or []),
    )
    state.news.append(article)
    state.news = state.news[-NEWS_CAP:]
    return article


def generate_week_roundup(state: CareerState, week: int) -> None:
    """Write the weekly news: the round-up, an upset, races, streaks and table talk."""
    played = _played_league_fixtures(state, week)
    if not played:
        return
    _upset_story(state, week, played)
    _result_roundup(state, week, played)
    _scoring_race(state, week)
    _streak_story(state, week)
    _table_narrative(state, week)


def generate_season_awards(state: CareerState, week: int) -> None:
    """Hand out the end-of-season player awards."""
    season = state.current_season
    stats = [
        p.season_stats[-1]
        for p in state.players.values()
        if p.season_stats and p.season_stats[-1].season == season and not p.retired
    ]
    by_apps = [s for s in stats if s.appearances >= 4]

    scorer = max(by_apps, key=lambda s: (s.goals, s.minutes_played)) if by_apps else None
    if scorer and scorer.goals >= 3:
        player = _player_of(state, scorer)
        add_news(
            state, NewsCategory.MATCH_RESULT,
            f"Golden Boot: {player.full_name} ({scorer.goals} goals)",
            (f"{player.full_name} of {_club_name(state, player)} finishes as the "
             f"{state.competitions[LEAGUE_ID].name}'s "
             f"top scorer with {scorer.goals} goals this season."),
            [player.club_id] if player.club_id else None, [player.id],
        )

    rated = [s for s in stats if s.ratings_count >= 15]
    if rated:
        best = max(rated, key=lambda s: (s.average_rating, s.appearances))
        player = _player_of(state, best)
        add_news(
            state, NewsCategory.GENERAL,
            f"Player of the season: {player.full_name}",
            (f"{player.full_name} (rating {best.average_rating:.1f}) is voted the season's "
             f"standout performer in the {state.competitions[LEAGUE_ID].name}."),
            [player.club_id] if player.club_id else None, [player.id],
        )
        young = [s for s in rated if _age(state, _player_of(state, s)) <= 21]
        if young:
            top = max(young, key=lambda s: (s.average_rating, s.appearances))
            kid = _player_of(state, top)
            add_news(
                state, NewsCategory.YOUNG_STAR,
                f"{kid.full_name} named Young Player of the Season",
                (f"At {_age(state, kid)}, {kid.full_name} has been the league's brightest young "
                 f"thing, averaging {top.average_rating:.1f} this season."),
                [kid.club_id] if kid.club_id else None, [kid.id],
            )


# ---------------------------------------------------------------------------
# Weekly desk helpers
# ---------------------------------------------------------------------------

def _played_league_fixtures(state: CareerState, week: int):
    return sorted(
        (f for f in state.fixtures
         if f.season == state.current_season
         and f.competition_id == LEAGUE_ID
         and f.week == week
         and f.score is not None),
        key=lambda f: f.id,
    )


def _upset_story(state: CareerState, week: int, played) -> None:
    best = None
    for f in played:
        if f.score[0] == f.score[1]:
            continue
        home, away = state.club(f.home_club_id), state.club(f.away_club_id)
        if home.reputation == away.reputation:
            continue
        if (f.score[0] > f.score[1]) != (home.reputation > away.reputation):
            gap = abs(home.reputation - away.reputation)
            if best is None or gap > best[0]:
                best = (gap, f, home if home.reputation < away.reputation else away,
                        home if home.reputation > away.reputation else away)
    if best is None:
        return
    _, f, giant, goliath = best
    gh, ga = f.score
    if state.user_club_id in (f.home_club_id, f.away_club_id):
        return
    add_news(
        state, NewsCategory.MATCH_RESULT,
        f"Stunner: {giant.name} topple {goliath.name}",
        (f"{giant.name} pulled off the result of the week, beating {goliath.name} {gh}-{ga} "
         f"in {goliath.name}'s own backyard." if f.home_club_id == goliath.id
         else f"{giant.name} stunned {goliath.name} with a {gh}-{ga} victory at home."),
        [f.home_club_id, f.away_club_id],
    )


def _result_roundup(state: CareerState, week: int, played) -> None:
    spread = state.competitions[LEAGUE_ID].name if LEAGUE_ID in state.competitions else "the league"
    lines = " \u00b7 ".join(
        f"{state.club(f.home_club_id).name} {f.score[0]}-{f.score[1]} {state.club(f.away_club_id).name}"
        for f in played
    )
    user_line = None
    for f in played:
        if state.user_club_id not in (f.home_club_id, f.away_club_id):
            continue
        home, away = state.club(f.home_club_id), state.club(f.away_club_id)
        mine = f.score[0] if f.home_club_id == state.user_club_id else f.score[1]
        other = f.score[1] if f.home_club_id == state.user_club_id else f.score[0]
        verb = "beat" if mine > other else ("drew with" if mine == other else "fell to")
        user_line = f" {state.user_club().name} {verb} {(away if f.home_club_id == state.user_club_id else home).name} {mine}-{other}."
    add_news(
        state, NewsCategory.MATCH_RESULT,
        f"Week {week} round-up",
        f"All {spread} results:{' ' + lines + '.' if lines else ''}" + (user_line or ""),
    )


def _scoring_race(state: CareerState, week: int) -> None:
    season = state.current_season
    leaders = []
    for p in state.players.values():
        if p.retired or not p.season_stats:
            continue
        s = p.season_stats[-1]
        if s.season != season or s.goals <= 0:
            continue
        leaders.append((s.goals, s.assists, s.minutes_played, p))
    if not leaders:
        return
    leaders.sort(key=lambda t: (-t[0], -t[1], t[2], t[3].id))
    goals, assists, _, player = leaders[0]
    if goals < 4:
        return
    category = NewsCategory.YOUNG_STAR if _age(state, player) <= 21 else NewsCategory.GENERAL
    add_news(
        state, category,
        f"{player.full_name} tops the scoring charts",
        (f"{player.full_name} leads {state.competitions[LEAGUE_ID].name} with {goals} goals "
         f"({assists} assists) after week {week}."),
        [player.club_id] if player.club_id else None, [player.id],
    )


def _streak_story(state: CareerState, week: int) -> None:
    runs = []
    for club in state.clubs.values():
        seq = _club_results(state, club.id)
        if not seq:
            continue
        count = 0
        current = seq[-1]
        for result in reversed(seq):
            if result == current:
                count += 1
            else:
                break
        if count >= 4 and current in ("W", "L"):
            runs.append((count, current, club.id))
    if not runs:
        return
    runs.sort(key=lambda t: (-t[0], t[2]))
    count, outcome, club_id = runs[0]
    club = state.club(club_id)
    if outcome == "W" and state.user_club_id == club_id:
        add_news(
            state, NewsCategory.STREAK,
            f"{club.name} unstoppable: four straight wins",
            f"{count} wins in a row — {club.name} are the form side in the division.",
            [club_id],
        )
    elif outcome == "W":
        add_news(
            state, NewsCategory.STREAK,
            f"{club.name} on fire: {count} straight wins",
            f"{club.name} have won {count} league games in a row and are building real momentum.",
            [club_id],
        )
    elif outcome == "L":
        add_news(
            state, NewsCategory.STREAK,
            f"{club.name} slump: {count} straight defeats",
            f"{club.name} have lost {count} consecutive league games — pressure is mounting.",
            [club_id],
        )


def _club_results(state: CareerState, club_id: str) -> list[str]:
    results = []
    for f in sorted(
        (f for f in state.fixtures
         if f.season == state.current_season
         and f.competition_id == LEAGUE_ID
         and club_id in (f.home_club_id, f.away_club_id)
         and f.score is not None),
        key=lambda x: (x.week, x.id),
    ):
        gh, ga = f.score
        mine = gh if f.home_club_id == club_id else ga
        other = ga if f.home_club_id == club_id else gh
        results.append("W" if mine > other else "L" if mine < other else "D")
    return results


def _table_narrative(state: CareerState, week: int) -> None:
    standings = compute_standings(state.fixtures)
    if len(standings) < 2:
        return
    leader, second = standings[0], standings[1]
    user_row = next((r for r in standings if r.club_id == state.user_club_id), None)
    position = standings.index(user_row) + 1 if user_row else None
    rng = SeededRng(state.seed)
    pick = rng.random(f"news_narrative_{state.current_season}_{week}")

    gap_top = leader.points - second.points
    if week >= 14 and gap_top <= 2 and pick < 0.6:
        add_news(
            state, NewsCategory.MATCH_RESULT,
            f"Title race heats up in {state.competitions[LEAGUE_ID].name}",
            (f"Just {gap_top} point{'s' if gap_top != 1 else ''} separate "
             f"{state.club(leader.club_id).name} at the top from {state.club(second.club_id).name}. "
             f"The run-in is going to be fascinating."),
            [leader.club_id, second.club_id],
        )
        return
    if user_row is None:
        return
    if position == 1:
        add_news(
            state, NewsCategory.MATCH_RESULT,
            f"{state.user_club().name} sit top of {state.competitions[LEAGUE_ID].name}",
            f"A {user_row.points}-point haul after week {week} has {state.user_club().name} leading "
            f"{state.club(second.club_id).name} by {gap_top} point{'s' if gap_top != 1 else ''}.",
            [state.user_club_id, second.club_id],
        )
    elif position >= 16 and week >= 8:
        add_news(
            state, NewsCategory.MATCH_RESULT,
            f"{state.user_club().name} in a relegation scrap",
            f"{state.user_club().name} sit {position}th with {user_row.points} points after week {week} — "
            f"every point from here counts.",
            [state.user_club_id],
        )


def _player_of(state: CareerState, stats) -> Player:
    for p in state.players.values():
        if p.season_stats and p.season_stats[-1] is stats:
            return p
    raise KeyError("stats belong to no known player")


def _age(state: CareerState, player: Player) -> int:
    return player.age_as_of(int(state.current_season.split("-")[0]))


def _club_name(state: CareerState, player: Player) -> str:
    if player.club_id and player.club_id in state.clubs:
        return state.club(player.club_id).name
    return "Free agency"