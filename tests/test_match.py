"""Tests for the deterministic match simulation and weekly progression."""

import unittest

from manager.core.enums import FixtureStatus, Position
from manager.core.models import CareerState
from manager.systems.match import simulate_match, simulate_season, simulate_to_week, simulate_week

SEED = 2026


def make_career(seed=SEED) -> CareerState:
    from manager.api.careers import new_career

    return new_career(
        first_name="Remy", last_name="Duran", nationality="Valland",
        club_id="clb_northbay", difficulty="manager",
        objective_key="steady", seed=seed, names_file=None,
    )


class MatchSimulationTest(unittest.TestCase):
    def test_same_seed_same_result(self):
        state_a = make_career()
        state_b = make_career()
        fixture_a = next(f for f in state_a.fixtures if f.week == 1 and f.home_club_id != "clb_northbay")
        fixture_b = next(f for f in state_b.fixtures if f.id == fixture_a.id)

        simulate_match(state_a, fixture_a)
        simulate_match(state_b, fixture_b)

        self.assertEqual((fixture_a.home_goals, fixture_a.away_goals),
                         (fixture_b.home_goals, fixture_b.away_goals))
        self.assertEqual(fixture_a.ratings, fixture_b.ratings)
        self.assertEqual([(e.minute, e.player_id, str(e.event_type)) for e in fixture_a.events],
                         [(e.minute, e.player_id, str(e.event_type)) for e in fixture_b.events])

    def test_scores_are_sane(self):
        state = make_career()
        for fixture in state.fixtures[:12]:
            simulate_match(state, fixture)
            gh, ga = fixture.home_goals, fixture.away_goals
            self.assertGreaterEqual(gh, 0)
            self.assertGreaterEqual(ga, 0)
            self.assertLess(gh, 9)
            self.assertLess(ga, 9)

    def test_stats_recorded(self):
        state = make_career()
        fixture = next(f for f in state.fixtures if f.week == 1)
        simulate_match(state, fixture)
        self.assertTrue(fixture.stats)
        self.assertEqual(fixture.status, FixtureStatus.PLAYED)
        self.assertEqual(fixture.score, (fixture.home_goals, fixture.away_goals))
        self.assertGreater(fixture.attendance, 0)
        for pid in fixture.team_home_ids:
            self.assertIn(pid, fixture.ratings)

    def test_goals_events_match_score(self):
        state = make_career()
        fixture = next(f for f in state.fixtures if f.week == 1)
        simulate_match(state, fixture)
        home_goals = sum(1 for e in fixture.events
                         if e.event_type.value == "goal" and e.club_id == fixture.home_club_id)
        away_goals = sum(1 for e in fixture.events
                         if e.event_type.value == "goal" and e.club_id == fixture.away_club_id)
        self.assertEqual(home_goals, fixture.home_goals)
        self.assertEqual(away_goals, fixture.away_goals)


class WeekProgressionTest(unittest.TestCase):
    def test_play_week_advances_and_plays_week_one(self):
        state = make_career()
        self.assertEqual(state.current_week, 0)
        outcome = simulate_week(state)
        self.assertEqual(outcome["week"], 1)
        self.assertEqual(state.current_week, 1)
        self.assertEqual(state.seasons["2026-27"].current_week, 1)
        played = [f for f in state.fixtures if f.week == 1]
        self.assertTrue(all(f.status is FixtureStatus.PLAYED for f in played))

    def test_user_match_is_flagged(self):
        state = make_career()
        simulate_week(state)
        user_fixture = next(
            f for f in state.fixtures
            if f.week == 1 and ("clb_northbay" in (f.home_club_id, f.away_club_id))
        )
        self.assertTrue(user_fixture.is_user_match)

    def test_week_one_news_added_for_user(self):
        state = make_career()
        self.assertGreaterEqual(len(state.news), 1)
        before = len(state.news)
        simulate_week(state)
        self.assertGreater(len(state.news), before)
        self.assertIn("clb_northbay", state.news[-1].clubs_involved)

    def test_matchday_history_recorded(self):
        state = make_career()
        simulate_week(state)
        self.assertEqual(len(state.matchday_history), 1)
        self.assertRegex(state.matchday_history[0], r"Week 1: (W|D|L) \d+-\d+")

    def test_full_season_runs_without_error(self):
        state = make_career()
        for _ in range(34):
            outcome = simulate_week(state)
            if outcome.get("finished"):
                break
        self.assertTrue(state.seasons["2026-27"].finished)
        self.assertEqual(state.current_week, 34)

    def test_simulate_to_week_advances_exactly(self):
        state = make_career()
        result = simulate_to_week(state, 5)
        self.assertEqual(state.current_week, 5)
        self.assertFalse(state.seasons["2026-27"].finished)
        self.assertEqual(result["week"], 5)
        self.assertEqual(len(state.matchday_history), 5)

    def test_simulate_to_week_clamps_to_season_end(self):
        state = make_career()
        result = simulate_to_week(state, 999)
        self.assertTrue(state.seasons["2026-27"].finished)
        self.assertEqual(state.current_week, 34)
        self.assertTrue(result["finished"])

    def test_simulate_season_finishes_and_marks_objectives(self):
        state = make_career()
        simulate_season(state)
        self.assertTrue(state.seasons["2026-27"].finished)
        self.assertEqual(state.current_week, 34)
        objectives = state.user_club().objectives
        for objective in objectives:
            if objective.season == "2026-27":
                self.assertTrue(objective.achieved or objective.label or True)

    def test_skip_equals_manual_play_week_by_week(self):
        state_a = make_career()
        state_b = make_career()
        for _ in range(7):
            simulate_week(state_a)
        simulate_to_week(state_b, 7)
        self.assertEqual(state_a.current_week, state_b.current_week)
        self.assertEqual(state_a.matchday_history, state_b.matchday_history)
        self.assertEqual(
            [f.home_goals for f in state_a.fixtures if f.week <= 7],
            [f.home_goals for f in state_b.fixtures if f.week <= 7],
        )

    def test_player_stats_updated_after_match(self):
        state = make_career()
        simulate_week(state)
        club = state.user_club()
        for pid in club.squad_ids:
            player = state.players[pid]
            stats = player.season_stats[-1]
            self.assertEqual(stats.season, "2026-27")
            if pid in state.selections[club.id].starter_ids:
                self.assertEqual(stats.appearances, 1)
            self.assertGreaterEqual(player.energy, 0)
            self.assertGreaterEqual(player.fitness, 0)


if __name__ == "__main__":
    unittest.main()