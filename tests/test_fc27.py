"""Tests for the FC27-style calendar and game plan (dates, pitch, mentality)."""

import unittest

from manager.core.enums import Mentality
from manager.systems.fixtures import LEAGUE_ID, generate_league_fixtures, matchday_date
from manager.systems.cup import CUP_ID, setup_cup


def make_career(seed: int = 2026) -> "CareerState":
    from manager.core.models import CareerState
    from manager.api.careers import new_career

    return new_career(
        first_name="Remy", last_name="Duran", nationality="Valland",
        club_id="clb_northbay", difficulty="manager",
        objective_key="steady", seed=seed, names_file=None,
    )


class FixtureDateTest(unittest.TestCase):
    def test_league_kicks_off_on_the_opening_saturday(self):
        fixtures = generate_league_fixtures(
            "2026-27", LEAGUE_ID, [f"clb_{i}" for i in range(12)])
        week1 = [f for f in fixtures if f.week == 1]
        self.assertTrue(week1)
        self.assertEqual(week1[0].date, "2026-08-01")
        self.assertTrue(all(f.date == "2026-08-01" for f in week1))

    def test_league_weeks_are_consecutive_saturdays(self):
        fixtures = generate_league_fixtures(
            "2026-27", LEAGUE_ID, [f"clb_{i}" for i in range(12)])
        by_week = {w: [f for f in fixtures if f.week == w][0] for w in (1, 2, 3)}
        dates = [by_week[w].date for w in (1, 2, 3)]
        self.assertEqual(dates, ["2026-08-01", "2026-08-08", "2026-08-15"])

    def test_cup_ties_are_midweek(self):
        league = matchday_date(2026, 2, LEAGUE_ID)
        cup = matchday_date(2026, 2, CUP_ID)
        self.assertEqual(league, "2026-08-08")
        self.assertEqual(cup, "2026-08-05")

    def test_rollover_fixtures_are_dated(self):
        from manager.systems.match import simulate_season
        from manager.systems.season import start_next_season

        state = make_career()
        simulate_season(state)
        start_next_season(state)
        league = [f for f in state.fixtures if f.competition_id == LEAGUE_ID and f.week == 1]
        cup = [f for f in state.fixtures if f.competition_id == CUP_ID and f.week == 2]
        self.assertTrue(league and all(f.date for f in league))
        self.assertTrue(cup and all(f.date for f in cup))


class MentalityTest(unittest.TestCase):
    def test_attacking_mentality_creates_more_than_defensive(self):
        from manager.systems.match import simulate_week

        attacking = make_career()
        defending = make_career()
        attacker = attacking.user_club()
        defender = defending.user_club()
        attacker.tactics.mentality = Mentality.ATTACKING
        defender.tactics.mentality = Mentality.DEFENSIVE

        user_fixture_id = next(
            f.id for f in attacking.fixtures
            if f.season == attacking.current_season
            and (f.home_club_id == attacking.user_club_id or f.away_club_id == attacking.user_club_id)
            and f.week == 1
        )
        simulate_week(attacking)
        simulate_week(defending)

        a = next(f for f in attacking.fixtures if f.id == user_fixture_id)
        d = next(f for f in defending.fixtures if f.id == user_fixture_id)
        my_a = a.stats.expected_goals_home if a.home_club_id == attacking.user_club_id else a.stats.expected_goals_away
        my_d = d.stats.expected_goals_home if d.home_club_id == defending.user_club_id else d.stats.expected_goals_away
        self.assertGreater(my_a, my_d)

    def test_mentality_survives_save_load(self):
        from manager.core.serialization import dump, load
        from manager.core.models import CareerState

        state = make_career()
        state.user_club().tactics.mentality = Mentality.ULTRA_ATTACKING
        restored = load(CareerState, dump(state))
        self.assertEqual(
            restored.user_club().tactics.mentality, Mentality.ULTRA_ATTACKING)


class GamePlanApiTest(unittest.TestCase):
    def make_service(self):
        from manager.api.service import GameService

        service = GameService()
        service.create_career({
            "first_name": "Remy", "last_name": "Duran",
            "nationality": "Valland", "club_id": "clb_northbay",
            "difficulty": "manager", "objective": "steady", "seed": 2026,
        })
        return service

    def test_game_plan_has_full_xi_laid_out(self):
        service = self.make_service()
        view = service.query("tactics", {})
        gp = view["game_plan"]
        total = sum(len(row["players"]) for row in gp["rows"])
        self.assertEqual(total, 11)
        gk_row = gp["rows"][0]
        self.assertEqual(gk_row["line"], "GK")
        self.assertEqual(len(gk_row["players"]), 1)
        for row in gp["rows"]:
            for card in row["players"]:
                self.assertIn("name", card)
                self.assertIn("overall", card)
                self.assertIn("position", card)
        self.assertLessEqual(len(gp["substitutes"]), 5)

    def test_mentality_option_available_and_settable(self):
        service = self.make_service()
        view = service.query("tactics", {})
        self.assertIn("mentality", view["options"])
        result = service.action("set_tactics", {"mentality": "attacking"})
        self.assertEqual(result["tactics"]["mentality"], "attacking")
        with self.assertRaises(Exception):
            service.action("set_tactics", {"mentality": "bogus"})

    def test_fixtures_view_has_dates_and_cup_competitions(self):
        service = self.make_service()
        view = service.query("fixtures", {})
        self.assertTrue(view["fixtures"])
        f = view["fixtures"][0]
        self.assertTrue(f["date"])
        self.assertTrue(f["date_label"])
        self.assertTrue(f["month"])
        comps = {row["competition"] for row in view["fixtures"]}
        self.assertIn("Continental Cup", comps)


if __name__ == "__main__":
    unittest.main()