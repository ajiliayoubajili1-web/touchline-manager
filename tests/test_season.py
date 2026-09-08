"""Tests for season rollover: aging, retirement, academy intake, new calendar."""
import unittest

from manager.api.careers import new_career
from manager.api.service import market_view
from manager.core.enums import FixtureStatus
from manager.core.models import CareerState
from manager.systems.match import simulate_season
from manager.systems.season import SeasonError, start_next_season


def finished_career(seed=2026) -> CareerState:
    state = new_career(
        first_name="Remy", last_name="Duran", nationality="Valland",
        club_id="clb_northbay", difficulty="manager",
        objective_key="steady", seed=seed, names_file=None,
    )
    simulate_season(state)
    return state


class RolloverTest(unittest.TestCase):
    def test_requires_finished_season(self):
        state = new_career(
            first_name="Remy", last_name="Duran", nationality="Valland",
            club_id="clb_northbay", difficulty="manager",
            objective_key="steady", seed=2026, names_file=None,
        )
        with self.assertRaises(SeasonError):
            start_next_season(state)

    def test_new_season_opens_next_year(self):
        state = finished_career()
        start_next_season(state)
        self.assertEqual(state.current_season, "2027-28")
        self.assertEqual(state.current_week, 0)
        season = state.seasons["2027-28"]
        self.assertFalse(season.finished)
        self.assertEqual(season.start_year, 2027)

    def test_calendars_regenerated(self):
        state = finished_career()
        start_next_season(state)
        league = [f for f in state.fixtures if f.competition_id == "apex_division"]
        cup = [f for f in state.fixtures if f.competition_id == "continental_series"]
        self.assertEqual(len(league), 306)
        self.assertEqual(len(cup), 8)
        self.assertTrue(all(f.season == "2027-28" for f in league))
        self.assertTrue(all(f.status is FixtureStatus.SCHEDULED for f in state.fixtures))

    def test_objectives_renewed_for_new_season(self):
        state = finished_career()
        start_next_season(state)
        objectives = state.user_club().objectives
        self.assertTrue(objectives)
        self.assertTrue(all(o.season == "2027-28" for o in objectives))
        self.assertTrue(all(not o.achieved for o in objectives))

    def test_squads_full_and_no_retired_in_lineup(self):
        state = finished_career()
        start_next_season(state)
        for club in state.clubs.values():
            self.assertEqual(len(club.squad_ids), 25, club.id)
            for pid in club.squad_ids:
                self.assertFalse(state.players[pid].retired, f"{pid} retired but still in squad")

    def test_market_hides_retired(self):
        state = finished_career()
        start_next_season(state)
        market = market_view(state)
        for target in market["targets"]:
            player = state.players[target["id"]]
            self.assertFalse(player.retired)

    def test_rollover_is_deterministic(self):
        a, b = finished_career(seed=7), finished_career(seed=7)
        start_next_season(a)
        start_next_season(b)
        self.assertEqual(
            sorted(p.id for p in a.players.values() if "_youth_" in p.id),
            sorted(p.id for p in b.players.values() if "_youth_" in p.id),
        )
        self.assertEqual(a.current_season, b.current_season)

    def test_user_selection_rebuilt_for_new_squad(self):
        state = finished_career()
        start_next_season(state)
        selection = state.selections[state.user_club_id]
        self.assertEqual(len(selection.starter_ids), 11)
        for pid in selection.starter_ids:
            self.assertIn(pid, state.user_club().squad_ids)

    def test_young_players_progress_season_to_season(self):
        state = new_career(
            first_name="Remy", last_name="Duran", nationality="Valland",
            club_id="clb_northbay", difficulty="manager",
            objective_key="steady", seed=2026, names_file=None,
        )
        season_year = int(state.current_season.split("-")[0])
        young = [p for p in state.players.values() if not p.retired and p.age_as_of(season_year) <= 23]
        before = {p.id: p.overall for p in young}

        simulate_season(state)
        start_next_season(state)

        for p in young:
            after = state.players[p.id]
            if after.retired:
                continue
            self.assertGreaterEqual(after.overall, before[p.id],
                                    f"{p.id} regressed across seasons")
        gains = sum(after.overall - before[p.id]
                    for p in young if not state.players[p.id].retired
                    for after in [state.players[p.id]])
        self.assertGreater(gains, 0, "young players should improve overall")

    def test_academy_intake_is_young_and_club_attached(self):
        state = finished_career()
        start_next_season(state)
        intake = [state.players[pid] for club in state.clubs.values() for pid in club.squad_ids
                  if pid in state.players and ("_youth_" in pid or "_aca_" in pid)]
        self.assertTrue(intake)
        new_year = int(state.current_season.split("-")[0])
        self.assertTrue(all(p.age_as_of(new_year) <= 19 for p in intake), "academy intake must be young")
        self.assertTrue(all(p.club_id for p in intake), "academy players must be attached to a club")
        market_view_state = market_view(state)
        declared = [t for t in market_view_state["targets"] if t["kind"] == "academy"]
        self.assertTrue(all(t["age"] <= 21 for t in declared))


class RolloverPersistenceTest(unittest.TestCase):
    def test_save_reload_then_second_season_plays(self):
        import shutil
        import tempfile
        import pathlib

        from manager.save.files import read_save, write_save
        from manager.systems.match import simulate_week

        state = finished_career(seed=99)
        start_next_season(state)
        save_dir = pathlib.Path(tempfile.mkdtemp(dir=pathlib.Path(r"C:\Users\adama\AppData\Local\Temp\opencode")))
        try:
            write_save(state, save_dir)
            reloaded = read_save(state.career_id, save_dir)
            self.assertEqual(reloaded.current_season, "2027-28")
            self.assertEqual(len(reloaded.selections[reloaded.user_club_id].starter_ids), 11)
            outcome = simulate_week(reloaded)
            self.assertEqual(outcome["week"], 1)
            self.assertEqual(reloaded.current_week, 1)
        finally:
            shutil.rmtree(save_dir, ignore_errors=True)

    def test_rollover_not_repeatable_without_playing(self):
        state = finished_career()
        start_next_season(state)
        with self.assertRaises(SeasonError):
            start_next_season(state)


if __name__ == "__main__":
    unittest.main()