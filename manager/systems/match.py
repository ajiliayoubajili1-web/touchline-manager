"""Deterministic match simulation.

A match is seeded from the career seed plus the fixture id, so the outcome is
fully reproducible after a save/load cycle. Team strength comes from the agreed
starting lineups (form, fitness and morale included); the user's picks feed the
user match, while AI clubs pick their best available eleven in their formation.
"""

from __future__ import annotations

import math

from manager.core.enums import FixtureStatus, MatchEventType, Mentality, Position
from manager.core.models import CareerState, Fixture, MatchEvent, MatchStats, Player, Season
from manager.rng import SeededRng
from manager.systems.squads import build_best_xi

LEAGUE_ID = "apex_division"

_SUBSTITUTE_BENCH = 5


def available(player: Player) -> bool:
    if player.injury is not None and player.injury.weeks_remaining > 0:
        return False
    if player.suspension is not None and player.suspension.matches_remaining > 0:
        return False
    return True


def resolve_lineup(state: CareerState, club_id: str, is_user: bool) -> list[str]:
    """Starting XI for a fixture, substituting unavailable players on the bench."""
    club = state.club(club_id)
    squad = [state.players[pid] for pid in club.squad_ids if pid in state.players]

    if is_user:
        selection = state.selections.get(club_id)
        picked = list(selection.starter_ids) if selection else []
        bench = list(selection.substitute_ids) if selection else []
    else:
        selection = build_best_xi(club_id, squad, club.tactics.formation, available_only=True)
        picked = list(selection.starter_ids)
        bench = list(selection.substitute_ids)

    lineup = []
    reserve = []
    for pid in picked + bench:
        player = state.players.get(pid)
        if player is None:
            continue
        if len(lineup) < 11 and available(player):
            lineup.append(pid)
        else:
            reserve.append(player)

    if len(lineup) < 11:
        for player in sorted(squad, key=lambda pl: -pl.overall):
            if player.id in lineup or player.id in picked and False:
                continue
            if len(lineup) >= 11:
                break
            if available(player):
                lineup.append(player.id)
    return lineup


def simulate_week(state: CareerState) -> dict:
    """Play every scheduled league fixture in the next week and roll state forward."""
    season = state.seasons[state.current_season]
    next_week = state.current_week + 1
    if season.finished:
        return {"finished": True, "week": state.current_week}

    week_fixtures = sorted(
        (f for f in state.fixtures
         if f.season == state.current_season
         and f.competition_id == LEAGUE_ID
         and f.week == next_week
         and f.status is FixtureStatus.SCHEDULED),
        key=lambda f: f.id,
    )

    for fixture in week_fixtures:
        is_user = (
            fixture.home_club_id == state.user_club_id
            or fixture.away_club_id == state.user_club_id
        )
        simulate_match(state, fixture, is_user=is_user)
        _apply_match(state, fixture)

    from manager.systems.cup import simulate_cup_week
    simulate_cup_week(state, next_week)

    _maintenance(state, next_week)

    from manager.systems.development import development_tick
    development_tick(state, next_week)

    state.current_week = next_week
    season.current_week = next_week
    if next_week >= season.total_weeks:
        season.finished = True

    from manager.systems.news import generate_season_awards, generate_week_roundup
    generate_week_roundup(state, next_week)
    if season.finished:
        generate_season_awards(state, next_week)

    _finish_week(state, next_week)
    return {"finished": season.finished, "week": next_week}


def simulate_to_week(state: CareerState, target_week: int) -> dict:
    """Fast-forward weekly simulation up to (and including) a target week."""
    season = state.seasons[state.current_season]
    target = max(season.current_week, min(int(target_week), season.total_weeks))
    guard = 0
    while state.current_week < target and not season.finished and guard < season.total_weeks:
        simulate_week(state)
        guard += 1
    return {"finished": season.finished, "week": state.current_week}


def simulate_season(state: CareerState) -> dict:
    """Simulate every remaining week of the current season."""
    return simulate_to_week(state, state.seasons[state.current_season].total_weeks)


def simulate_match(state: CareerState, fixture: Fixture, is_user: bool = False) -> Fixture:
    """Simulate one fixture in place (idempotent for a given fixture + state)."""
    rng = SeededRng(state.seed)

    home_ids = resolve_lineup(state, fixture.home_club_id, is_user and fixture.home_club_id == state.user_club_id)
    away_ids = resolve_lineup(state, fixture.away_club_id, is_user and fixture.away_club_id == state.user_club_id)

    home_players = [state.players[pid] for pid in home_ids]
    away_players = [state.players[pid] for pid in away_ids]

    home_strength = _team_strength(home_players)
    away_strength = _team_strength(away_players)
    if home_strength <= 0:
        home_strength = 1.0
    if away_strength <= 0:
        away_strength = 1.0

    xg_home, xg_away, possession = _match_expectations(home_strength, away_strength)

    home_mind, away_mind = _mentalities(state, fixture)
    home_own, home_opp = _mentality_factors(home_mind)
    away_own, away_opp = _mentality_factors(away_mind)
    xg_home = _clamp(xg_home * home_own * away_opp, 0.15, 4.0)
    xg_away = _clamp(xg_away * away_own * home_opp, 0.15, 4.0)
    possession = _clamp(possession + _mentality_possession(home_mind) - _mentality_possession(away_mind), 20.0, 80.0)

    home_goals = _poisson(rng, xg_home, f"match_{fixture.id}_home")
    away_goals = _poisson(rng, xg_away, f"match_{fixture.id}_away")

    shots_home = _poisson(rng, xg_home * 3.1, f"match_{fixture.id}_shots_h")
    shots_away = _poisson(rng, xg_away * 3.1, f"match_{fixture.id}_shots_a")
    corners_home = _poisson(rng, 4.4 * possession / 50.0, f"match_{fixture.id}_cor_h")
    corners_away = _poisson(rng, 4.4 * (100 - possession) / 50.0, f"match_{fixture.id}_cor_a")
    fouls_home = _poisson(rng, 11.0, f"match_{fixture.id}_foul_h")
    fouls_away = _poisson(rng, 11.0, f"match_{fixture.id}_foul_a")

    yc_home = _poisson(rng, 2.1, f"match_{fixture.id}_yc_h")
    yc_away = _poisson(rng, 2.1, f"match_{fixture.id}_yc_a")
    rc_home = 1 if rng.random(f"match_{fixture.id}_rc_h") < 0.045 else 0
    rc_away = 1 if rng.random(f"match_{fixture.id}_rc_a") < 0.045 else 0

    stats = MatchStats(
        possession_home=round(possession, 1),
        possession_away=round(100 - possession, 1),
        shots_home=shots_home,
        shots_away=shots_away,
        shots_on_target_home=_on_target(shots_home, home_goals),
        shots_on_target_away=_on_target(shots_away, away_goals),
        corners_home=corners_home,
        corners_away=corners_away,
        fouls_home=fouls_home,
        fouls_away=fouls_away,
        expected_goals_home=round(xg_home, 2),
        expected_goals_away=round(xg_away, 2),
    )

    events = _build_events(rng, fixture, home_players, away_players, home_goals, away_goals,
                           yc_home, yc_away, rc_home, rc_away)

    attendance = _attendance(rng, state, fixture)

    ratings = _ratings(rng, fixture, home_players, away_players, home_goals, away_goals,
                       events, possession)

    fixture.team_home_ids = home_ids
    fixture.team_away_ids = away_ids
    fixture.home_goals = home_goals
    fixture.away_goals = away_goals
    fixture.status = FixtureStatus.PLAYED
    fixture.events = sorted(events, key=lambda ev: ev.minute)
    fixture.stats = stats
    fixture.ratings = ratings
    fixture.attendance = attendance
    fixture.is_user_match = is_user
    return fixture


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _team_strength(players: list[Player]) -> float:
    if not players:
        return 0.0
    return sum(_effective(player) for player in players) / len(players)


def _match_expectations(home_strength: float, away_strength: float) -> tuple[float, float, float]:
    """Simple, logical goal model: each point of XI quality means ~0.10 more goals.

    The better side is expected to score more; a small home advantage tips close
    games; the weaker side is never anchored at zero so upsets stay possible but
    rare enough to feel earned.
    """
    gap = max(-20.0, min(20.0, home_strength - away_strength))
    xg_home = _clamp(1.35 + gap * 0.10 + 0.18, 0.15, 4.0)
    xg_away = _clamp(1.35 - gap * 0.10, 0.15, 4.0)
    possession = 50.0 + _clamp(gap * 2.0, -18.0, 18.0)
    return xg_home, xg_away, possession


def _mentalities(state: CareerState, fixture: Fixture) -> tuple[Mentality, Mentality]:
    home = state.club(fixture.home_club_id).tactics.mentality
    away = state.club(fixture.away_club_id).tactics.mentality
    return home, away


def _mentality_factors(mentality: Mentality) -> tuple[float, float]:
    """(own goals multiplier, opponent goals multiplier) for a game-plan mindset."""
    return {
        Mentality.ULTRA_DEFENSIVE: (0.86, 0.78),
        Mentality.DEFENSIVE: (0.93, 0.89),
        Mentality.BALANCED: (1.0, 1.0),
        Mentality.ATTACKING: (1.10, 1.05),
        Mentality.ULTRA_ATTACKING: (1.18, 1.10),
    }.get(mentality, (1.0, 1.0))


def _mentality_possession(mentality: Mentality) -> float:
    return {
        Mentality.ULTRA_DEFENSIVE: -2.6,
        Mentality.DEFENSIVE: -1.6,
        Mentality.BALANCED: 0.0,
        Mentality.ATTACKING: 1.6,
        Mentality.ULTRA_ATTACKING: 2.6,
    }.get(mentality, 0.0)


def _on_target(shots: int, goals: int) -> int:
    """Shots on target always sits between the goals scored and total shots."""
    return min(shots, goals + round(max(0, shots - goals) * 0.35))


def _effective(player: Player) -> float:
    if not available(player):
        return player.overall * 0.05
    fitness_factor = 0.70 + 0.30 * player.fitness / 100.0
    morale_factor = 0.75 + 0.25 * player.morale / 100.0
    return player.overall * fitness_factor * morale_factor


def _poisson(rng: SeededRng, lam: float, stream: str) -> int:
    lam = _clamp(lam, 0.05, 4.0)
    threshold = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random(stream)
        if p <= threshold or k > 30:
            break
    return max(0, k - 1)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _scorer_weights(players: list[Player]) -> list[float]:
    weights = []
    for player in players:
        pos = player.preferred_position
        if pos in (Position.LW, Position.RW, Position.CF, Position.ST):
            weight = 4.0
        elif pos in (Position.AM, Position.LM, Position.RM, Position.CM):
            weight = 2.0
        elif pos in (Position.DM,):
            weight = 0.6
        elif pos in (Position.LB, Position.CB, Position.RB, Position.WB):
            weight = 0.35
        else:
            weight = 0.05
        weights.append(weight * (0.6 + player.overall / 100.0))
    return [w * _role_goal_factor(player) for player, w in zip(players, weights)]


def _role_goal_factor(player: Player) -> float:
    """Tactical duty/role bias who gets on the scoresheet."""
    duty = str(player.tactical_duty)
    role = player.tactical_role
    if duty == "attack":
        return 1.5
    if duty == "support":
        return 1.1
    if duty == "defend":
        return 0.25
    if role in ("poacher", "target_man"):
        return 1.4
    if role in ("striker", "winger", "inverted", "wide_playmaker"):
        return 1.2
    return 1.0


def _pick_scorer(rng: SeededRng, players: list[Player], stream: str) -> Player:
    weights = _scorer_weights(players)
    return rng.choices(players, weights=weights, k=1, stream=stream)[0]


def _assist_for(rng: SeededRng, scorer_id: str, players: list[Player], stream: str) -> str | None:
    options = [
        p for p in players
        if p.id != scorer_id and p.preferred_position != Position.GK
    ]
    if not options:
        return None
    return rng.choice(options, stream=stream).id


def _build_events(rng, fixture, home_players, away_players, home_goals, away_goals,
                  yc_home, yc_away, rc_home, rc_away) -> list[MatchEvent]:
    events: list[MatchEvent] = []

    def team_goals(club_id: str, players: list[Player], goals: int, stream: str) -> None:
        for _ in range(goals):
            minute = rng.randint(1, 90, stream)
            scorer = _pick_scorer(rng, players, f"{stream}_scorer")
            assist = _assist_for(rng, scorer.id, players, f"{stream}_assist")
            events.append(MatchEvent(
                minute=minute,
                club_id=club_id,
                player_id=scorer.id,
                event_type=MatchEventType.GOAL,
                secondary_player_id=assist,
            ))

    team_goals(fixture.home_club_id, home_players, home_goals, f"match_{fixture.id}_gh")
    team_goals(fixture.away_club_id, away_players, away_goals, f"match_{fixture.id}_ga")

    _cards(rng, fixture.home_club_id, home_players, yc_home, rc_home, f"match_{fixture.id}_ch", events)
    _cards(rng, fixture.away_club_id, away_players, yc_away, rc_away, f"match_{fixture.id}_ca", events)
    return events


def _cards(rng, club_id, players, yellows, reds, stream, events) -> None:
    for _ in range(yellows):
        player = rng.choice(players, stream=stream)
        events.append(MatchEvent(
            minute=rng.randint(1, 90, f"{stream}_min"),
            club_id=club_id,
            player_id=player.id,
            event_type=MatchEventType.YELLOW_CARD,
        ))
    for _ in range(reds):
        player = rng.choice(players, stream=stream)
        events.append(MatchEvent(
            minute=rng.randint(1, 90, f"{stream}_rmin"),
            club_id=club_id,
            player_id=player.id,
            event_type=MatchEventType.RED_CARD,
        ))


def _attendance(rng: SeededRng, state: CareerState, fixture: Fixture) -> int:
    home = state.club(fixture.home_club_id)
    away = state.club(fixture.away_club_id)
    popularity = home.reputation * 0.65 + away.reputation * 0.35
    factor = _clamp(0.55 + popularity * 0.006, 0.55, 0.98)
    noise = rng.uniform(0.94, 1.06, f"match_{fixture.id}_att")
    return int(home.capacity * factor * noise)


def _ratings(rng, fixture, home_players, away_players, home_goals, away_goals,
             events, possession) -> dict[str, float]:
    ratings: dict[str, float] = {}

    def side(players, goals_for, goals_against, home: bool) -> None:
        if goals_for > goals_against:
            mood = 0.45
        elif goals_for == goals_against:
            mood = 0.05
        else:
            mood = -0.35
        for player in players:
            base = 6.35 + mood
            jitter = rng.gauss(0.0, 0.45, f"match_{fixture.id}_rat")
            ratings[player.id] = _clamp(round(base + jitter, 1), 4.0, 9.5)

    side(home_players, home_goals, away_goals, True)
    side(away_players, away_goals, home_goals, False)

    for event in events:
        if event.event_type is MatchEventType.GOAL:
            if event.player_id in ratings:
                ratings[event.player_id] = _clamp(ratings[event.player_id] + 1.2, 1.0, 9.9)
            if event.secondary_player_id in ratings:
                ratings[event.secondary_player_id] = _clamp(
                    ratings[event.secondary_player_id] + 0.8, 1.0, 9.9)
        if event.event_type is MatchEventType.RED_CARD and event.player_id in ratings:
            ratings[event.player_id] = _clamp(ratings[event.player_id] - 2.2, 1.0, 9.9)
        if event.event_type is MatchEventType.YELLOW_CARD and event.player_id in ratings:
            ratings[event.player_id] = _clamp(ratings[event.player_id] - 0.25, 1.0, 9.9)
    return ratings


# ---------------------------------------------------------------------------
# Post-match bookkeeping
# ---------------------------------------------------------------------------

def _stats_for(player: Player, season: str):
    for stats in player.season_stats:
        if stats.season == season:
            return stats
    from manager.core.models import PlayerSeasonStats

    stats = PlayerSeasonStats(season=season)
    player.season_stats.append(stats)
    return stats


def _apply_match(state: CareerState, fixture: Fixture) -> None:
    season = fixture.season
    home_squad = state.club(fixture.home_club_id).squad_ids
    away_squad = state.club(fixture.away_club_id).squad_ids
    home_won = fixture.score[0] > fixture.score[1]
    drew = fixture.score[0] == fixture.score[1]

    def apply_side(squad_ids: list[str], goals_for: int, goals_against: int, won: bool, lost: bool) -> None:
        for pid in squad_ids:
            player = state.players[pid]
            stats = _stats_for(player, season)
            if pid in fixture.team_home_ids or pid in fixture.team_away_ids:
                stats.appearances += 1
                stats.starts += 1
                stats.minutes_played += 90
                player.career_appearances += 1
            rating = fixture.ratings.get(pid)
            if rating is not None:
                stats.ratings_count += 1
                stats.average_rating = round(
                    (stats.average_rating * (stats.ratings_count - 1) + rating) / stats.ratings_count, 2)
                if won:
                    player.form = _clamp(player.form + int((rating - 6.0) * 2) + 3, 0, 100)
                elif lost:
                    player.form = _clamp(player.form + int((rating - 6.0) * 2) - 2, 0, 100)
                else:
                    player.form = _clamp(player.form + int((rating - 6.0) * 2), 0, 100)

            if pid in fixture.team_home_ids or pid in fixture.team_away_ids:
                player.energy = max(0, player.energy - 28)
                player.fitness = max(0, player.fitness - 3)
            else:
                player.energy = max(0, player.energy - 8)

            if player.preferred_position == Position.GK or Position.GK in player.positions:
                stats.goals_conceded += goals_against
                if goals_against == 0 and (pid in fixture.team_home_ids or pid in fixture.team_away_ids):
                    stats.clean_sheets += 1

            if won and player.club_id and (player.preferred_position != Position.GK):
                player.morale = min(100, player.morale + 3)
            elif lost:
                player.morale = max(0, player.morale - 3)
            elif drew and player.preferred_position != Position.GK:
                player.morale = min(100, player.morale + 1)

    apply_side(home_squad, fixture.home_goals, fixture.away_goals, home_won, not home_won and not drew)
    apply_side(away_squad, fixture.away_goals, fixture.home_goals, not home_won and not drew, home_won)

    for event in fixture.events:
        if event.event_type is MatchEventType.GOAL:
            scorer = state.players[event.player_id]
            _stats_for(scorer, season).goals += 1
            scorer.career_goals += 1
            scorer.form = min(100, scorer.form + 2)
            if event.secondary_player_id:
                assister = state.players[event.secondary_player_id]
                _stats_for(assister, season).assists += 1
                assister.career_assists += 1
        elif event.event_type is MatchEventType.YELLOW_CARD:
            _stats_for(state.players[event.player_id], season).yellow_cards += 1
        elif event.event_type is MatchEventType.RED_CARD:
            player = state.players[event.player_id]
            _stats_for(player, season).red_cards += 1
            if player.suspension is None:
                from manager.core.models import Suspension

                player.suspension = Suspension(matches_remaining=1, reason="Red card")


def apply_match_results(state: CareerState, fixture: Fixture) -> None:
    """Public wrapper: apply a finished match's bookkeeping to squads/players."""
    _apply_match(state, fixture)


def _maintenance(state: CareerState, week: int) -> None:
    for player in state.players.values():
        if player.club_id and player.club_id in state.clubs:
            player.energy = min(100, player.energy + 15)
            player.fitness = min(100, player.fitness + 3)
        if player.injury is not None:
            player.injury.weeks_remaining -= 1
            if player.injury.weeks_remaining <= 0:
                player.injury = None
        if player.suspension is not None:
            player.suspension.matches_remaining -= 1
            if player.suspension.matches_remaining <= 0:
                player.suspension = None


def _finish_week(state: CareerState, week: int) -> None:
    from manager.core.enums import NewsCategory
    from manager.core.models import NewsArticle

    user_fixtures = [
        f for f in state.fixtures
        if f.season == state.current_season
        and f.week == week
        and (f.home_club_id == state.user_club_id or f.away_club_id == state.user_club_id)
    ]
    for fixture in user_fixtures:
        home = state.club(fixture.home_club_id)
        away = state.club(fixture.away_club_id)
        if fixture.status is FixtureStatus.PLAYED and fixture.score:
            result = ("beat" if fixture.score[0] > fixture.score[1] and fixture.home_club_id == state.user_club_id
                      else "beat" if fixture.score[1] > fixture.score[0] and fixture.away_club_id == state.user_club_id
                      else "drew with")
            opp = (
                away.name if fixture.home_club_id == state.user_club_id else home.name
            )
            own = fixture.score[0] if fixture.home_club_id == state.user_club_id else fixture.score[1]
            other = fixture.score[1] if fixture.home_club_id == state.user_club_id else fixture.score[0]
            headline = f"{home.name} {fixture.score[0]}-{fixture.score[1]} {away.name}"
            body = f"{state.user_club().name} {result} {opp} {own}-{other}."
            state.news.append(NewsArticle(
                id=f"news_{state.current_season}_w{week}_{fixture.id}",
                season=state.current_season,
                week=week,
                category=NewsCategory.MATCH_RESULT,
                headline=headline,
                body=body,
                clubs_involved=[fixture.home_club_id, fixture.away_club_id],
                players_involved=[],
            ))
    state.news = state.news[-80:]

    summary = _week_summary(state, week)
    if summary:
        state.matchday_history.append(summary)

    if week >= state.seasons[state.current_season].total_weeks:
        _settle_season_objectives(state)


def _settle_season_objectives(state: CareerState) -> None:
    from manager.systems.fixtures import compute_standings

    standings = compute_standings(state.fixtures)
    position = next(
        (index + 1 for index, row in enumerate(standings) if row.club_id == state.user_club_id),
        None,
    )
    for objective in state.user_club().objectives:
        if objective.season == state.current_season and not objective.achieved:
            objective.achieved = objective.met({"league_position": position})

    _settle_titles(state, position)


def _settle_titles(state: CareerState, position: int | None) -> None:
    from manager.systems.cup import cup_champion

    club = state.user_club()
    titles = []
    if position == 1:
        trophy = state.competitions["apex_division"].trophy_name or "League"
        titles.append(f"{trophy}")
    from manager.core.enums import NewsCategory
    from manager.core.models import NewsArticle

    if cup_champion(state) == state.user_club_id:
        titles.append(state.competitions["continental_series"].trophy_name)

    if titles:
        state.news.append(NewsArticle(
            id=f"news_{state.current_season}_end_titles",
            season=state.current_season,
            week=state.seasons[state.current_season].total_weeks,
            category=NewsCategory.MATCH_RESULT,
            headline=f"{club.name} lift the {', '.join(titles)}!",
            body="A season to remember across the continent.",
            clubs_involved=[club.id],
        ))
        state.news = state.news[-80:]


def _week_summary(state: CareerState, week: int) -> str:
    mine = [
        f for f in state.fixtures
        if f.season == state.current_season and f.week == week
        and (f.home_club_id == state.user_club_id or f.away_club_id == state.user_club_id)
        and f.score is not None
    ]
    if not mine:
        return f"Week {week}: no match"
    fixture = mine[0]
    home = state.club(fixture.home_club_id)
    away = state.club(fixture.away_club_id)
    letter = "W" if (
        (fixture.home_club_id == state.user_club_id and fixture.score[0] > fixture.score[1])
        or (fixture.away_club_id == state.user_club_id and fixture.score[1] > fixture.score[0])
    ) else "D" if fixture.score[0] == fixture.score[1] else "L"
    opp = away.name if fixture.home_club_id == state.user_club_id else home.name
    return f"Week {week}: {letter} {fixture.score[0]}-{fixture.score[1]} vs {opp}"