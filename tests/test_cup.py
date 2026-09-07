"""Tests for the Continental Cup knockout tournament."""
import unittest

from manager.api.careers import new_career
from manager.core.enums import FixtureStatus
from manager.core.models import CareerState
from manager.systems.cup import CUP_ID, simulate_cup_week
from manager.systems.match import simulate_season, simulate_week


def make_career(seed=2026) -> CareerState:
    return new_career(
        first_name="Remy", last_name="Duran", nationality="Valland",
        club_id="clb_northbay", difficulty="manager",
        objective_key="steady", seed=seed, names_file=None,
    )


def cup(state, round_key=None):
    fixtures = [f for f in state.fixtures if f.competition_id == CUP_ID and f.season == state.current_season]
    if round_key:
        fixtures = [f for f in fixtures if f.round == round_key]
    return fixtures


class CupSetupTest(unittest.TestCase):
    def test_sixteen_teams_single_leg_round_of_16(self):
        state = make_career()
        ties = cup(state, "round_of_16")
        self.assertEqual(len(ties), 8)
        clubs = [c for f in ties for c in (f.home_club_id, f.away_club_id)]
        self.assertEqual(len(set(clubs)), 16)
        self.assertIn("clb_northbay", clubs)
        self.assertTrue(all(f.round == "round_of_16" for f in ties))
        self.assertTrue(all(f.week == 2 for f in ties))
        self.assertTrue(all(f.score is None for f in ties))

    def test_round_of_16_draw_is_deterministic(self):
        a = make_career(seed=7)
        b = make_career(seed=7)
        self.assertEqual([(f.home_club_id, f.away_club_id) for f in cup(a, "round_of_16")],
                         [(f.home_club_id, f.away_club_id) for f in cup(b, "round_of_16")])

    def test_league_fixtures_unaffected_counts(self):
        state = make_career()
        league = [f for f in state.fixtures if f.competition_id == "apex_division"]
        self.assertEqual(len(league), 306)
        self.assertEqual(len({f.week for f in league}), 34)

    def test_user_always_entered(self):
        state = make_career()
        mine = [f for f in cup(state, "round_of_16")
                if f.home_club_id == "clb_northbay" or f.away_club_id == "clb_northbay"]
        self.assertEqual(len(mine), 1)


class CupMatchTest(unittest.TestCase):
    @staticmethod
    def play_to_r16_result(state):
        simulate_week(state)
        simulate_week(state)

    def test_week_two_plays_r16_and_creates_quarters(self):
        state = make_career()
        self.play_to_r16_result(state)
        r16 = cup(state, "round_of_16")
        self.assertTrue(all(f.status is FixtureStatus.PLAYED for f in r16))
        self.assertFalse(any(f.winner_id is None for f in r16))
        quarters = cup(state, "quarter_final")
        self.assertEqual(len(quarters), 4)
        self.assertTrue(all(f.week == 8 for f in quarters))

    def test_r16_champion_advises_quarters_spots(self):
        state = make_career()
        self.play_to_r16_result(state)
        winners = {f.winner_id for f in cup(state, "round_of_16")}
        quarter_teams = {c for f in cup(state, "quarter_final") for c in (f.home_club_id, f.away_club_id)}
        self.assertEqual(winners, quarter_teams)

    def test_cup_is_deterministic_week_by_week(self):
        a, b = make_career(), make_career()
        self.play_to_r16_result(a)
        self.play_to_r16_result(b)
        self.assertEqual([(f.id, f.winner_id) for f in cup(a)],
                         [(f.id, f.winner_id) for f in cup(b)])

    def test_user_advance_news_written(self):
        state = make_career()
        self.play_to_r16_result(state)
        mine = next(f for f in cup(state, "round_of_16")
                    if f.home_club_id == "clb_northbay" or f.away_club_id == "clb_northbay")
        relevant = [n for n in state.news if mine.id in n.id]
        self.assertGreaterEqual(len(relevant), 1)
        self.assertTrue(any("Continental Cup" in n.headline for n in relevant))


class CupFullSeasonTest(unittest.TestCase):
    def test_champion_crowned_only_after_final(self):
        state = make_career()
        simulate_week(state)  # week 1
        simulate_week(state)  # week 2 -> quarters
        simulate_week(state)  # week 3
        finals = cup(state, "final")
        self.assertEqual(finals, [])
        champion_before = [f for f in cup(state) if f.round == "final" and f.winner_id]
        self.assertEqual(champion_before, [])

    def test_full_season_crowns_continental_champion(self):
        from manager.systems.cup import cup_champion
        from manager.systems.match import simulate_season

        state = make_career()
        simulate_season(state)
        self.assertTrue(state.seasons[state.current_season].finished)
        winner = cup_champion(state)
        self.assertIsNotNone(winner)
        final = next(f for f in cup(state, "final"))
        self.assertEqual(final.winner_id, winner)
        self.assertTrue(all(
            f.winner_id is not None for f in cup(state) if f.round != "final"
        ))

    def test_round_creation_is_idempotent_across_reload(self):
        import shutil
        import tempfile
        import pathlib

        from manager.save.files import read_save, write_save

        state = make_career()
        simulate_season(state)
        blob_before = {f.id: f.winner_id for f in cup(state, "quarter_final")}
        save_dir = pathlib.Path(tempfile.mkdtemp(dir=pathlib.Path(r"C:\Users\adama\AppData\Local\Temp\opencode")))
        try:
            write_save(state, save_dir)
            reloaded = read_save(state.career_id, save_dir)
            blob_after = {f.id: f.winner_id for f in cup(reloaded, "quarter_final")}
            self.assertEqual(blob_before, blob_after)
            self.assertEqual(len(cup(reloaded, "round_of_16")), 8)
            self.assertEqual(len(cup(reloaded, "quarter_final")), 4)
        finally:
            shutil.rmtree(save_dir, ignore_errors=True)

    def test_league_and_cup_titles_celebrated(self):
        from manager.core.enums import FixtureStatus
        from manager.systems.match import _settle_season_objectives

        state = make_career()
        simulate_season(state)
        for f in state.fixtures:
            if f.competition_id == "apex_division":
                f.status = FixtureStatus.PLAYED
                if state.user_club_id in (f.home_club_id, f.away_club_id):
                    is_home = f.home_club_id == state.user_club_id
                    f.home_goals, f.away_goals = (1, 0) if is_home else (0, 1)

        final = next(f for f in cup(state, "final"))
        final.winner_id = state.user_club_id

        _settle_season_objectives(state)
        headlines = [n.headline for n in state.news]
        self.assertTrue(any("Super League Trophy" in h and "Continental Cup" in h for h in headlines))
        objective = state.user_club().objectives[0]
        self.assertTrue(objective.achieved)


if __name__ == "__main__":
    unittest.main()