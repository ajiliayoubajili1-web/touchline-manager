"""Tests for the favourite-coach tactical identity feature."""

import unittest
from pathlib import Path

from manager.core.enums import Mentality, PlayingStyle
from manager.api.careers import new_career
from manager.api.service import GameService
from manager.data.coaches import COACH_PROFILES, coach_by_key, coach_tactics, roster


def make_career(coach_key: str = "") -> "CareerState":
    return new_career(
        first_name="Remy", last_name="Duran", nationality="Valland",
        club_id="clb_northbay", difficulty="manager",
        objective_key="steady", seed=2026, favourite_coach=coach_key,
        names_file=None,
    )


class CoachRosterTest(unittest.TestCase):
    def test_roster_has_five_iconic_coaches(self):
        rows = roster()
        self.assertEqual(len(rows), 5)
        names = {r["name"] for r in rows}
        self.assertEqual(
            names,
            {"Pep Guardiola", "José Mourinho", "Sir Alex Ferguson",
             "Carlo Ancelotti", "Zinedine Zidane"},
        )

    def test_profiles_carry_full_tactics(self):
        self.assertEqual(coach_tactics("pep_guardiola").mentality, Mentality.ATTACKING)
        self.assertEqual(coach_tactics("pep_guardiola").playing_style, PlayingStyle.CONTROLLED_POSSESSION)
        self.assertEqual(coach_tactics("jose_mourinho").mentality, Mentality.DEFENSIVE)
        self.assertEqual(coach_tactics("jose_mourinho").playing_style, PlayingStyle.FAST_COUNTER)

    def test_unknown_coach_looks_up_null(self):
        self.assertIsNone(coach_by_key("nobody"))
        self.assertIsNone(coach_tactics("nobody"))


class CoachCareerTest(unittest.TestCase):
    def test_chosen_coach_sets_club_default_tactics(self):
        state = make_career("jose_mourinho")
        club = state.user_club()
        self.assertEqual(club.tactics.mentality, Mentality.DEFENSIVE)
        self.assertEqual(club.tactics.playing_style, PlayingStyle.FAST_COUNTER)
        self.assertEqual(state.manager.favourite_coach, "jose_mourinho")

    def test_mourinho_profile_is_deep_but_not_ultra(self):
        state = make_career("jose_mourinho")
        tactics = state.user_club().tactics
        self.assertEqual(str(tactics.defensive_line), "deep")
        self.assertEqual(str(tactics.pressing), "low")

    def test_guardiola_profile_is_possession_based(self):
        state = make_career("pep_guardiola")
        tactics = state.user_club().tactics
        self.assertEqual(str(tactics.passing), "short")
        self.assertEqual(str(tactics.defensive_line), "high")
        self.assertEqual(str(tactics.pressing), "high")

    def test_no_coach_keeps_defaults(self):
        state = make_career("")
        self.assertEqual(state.user_club().tactics.mentality, Mentality.BALANCED)
        self.assertEqual(state.manager.favourite_coach, "")

    def test_unknown_coach_is_ignored_gracefully(self):
        state = make_career("bogus_coach")
        self.assertEqual(state.manager.favourite_coach, "")
        self.assertEqual(state.user_club().tactics.mentality, Mentality.BALANCED)

    def test_manager_tactics_formation_matches_coach_profile(self):
        state = make_career("sir_alex_ferguson")
        self.assertEqual(state.user_club().tactics.formation, "4-4-2")
        self.assertEqual(state.manager.tactics.formation, "4-4-2")

    def test_coach_persists_across_save_round_trip(self):
        from manager.save.files import write_save, read_save
        from manager.save.files import DEFAULT_SAVE_DIR
        import shutil

        tmp = Path(DEFAULT_SAVE_DIR) / "_coach_test_tmp"
        shutil.rmtree(tmp, ignore_errors=True)

        state = make_career("carlo_ancelotti")
        write_save(state, save_dir=tmp)
        restored = read_save(state.career_id, save_dir=tmp)
        shutil.rmtree(tmp, ignore_errors=True)

        self.assertEqual(restored.manager.favourite_coach, "carlo_ancelotti")
        self.assertEqual(restored.user_club().tactics.playing_style, PlayingStyle.CONTROLLED_POSSESSION)


class CoachApiTest(unittest.TestCase):
    def test_setup_view_exposes_coach_roster(self):
        service = GameService()
        setup = service.query("setup", {"seed": 42})
        self.assertEqual(len(setup["coaches"]), 5)
        self.assertEqual(setup["coaches"][0]["name"], "Pep Guardiola")

    def test_creating_career_with_coach_via_api(self):
        service = GameService()
        data = service.create_career({
            "first_name": "Avery",
            "last_name": "Cole",
            "nationality": "Valland",
            "club_id": "clb_liverpool",
            "difficulty": "manager",
            "objective": "steady",
            "seed": 42,
            "favourite_coach": "zinedine_zidane",
        })
        self.assertEqual(data["manager"]["favourite_coach"], "zinedine_zidane")
        self.assertEqual(data["manager"]["favourite_coach_name"], "Zinedine Zidane")
        self.assertEqual(data["club"]["name"], "Liverpool")


if __name__ == "__main__":
    unittest.main()