"""Tests for career creation, difficulty, objectives, and save/load."""

import tempfile
import unittest
from pathlib import Path

from manager.api.careers import CareerError, new_career, save_new_career
from manager.core.enums import Difficulty, Position
from manager.core.models import Player
from manager.core.validate import ValidationError, validate_squad_selection
from manager.save.files import read_save
from manager.systems.squads import build_best_xi, position_band

SEED = 77


def band_counts(formation: str) -> dict[str, int]:
    from manager.core.validate import parse_formation

    defenders, midfielders, forwards = parse_formation(formation)
    return {"GK": 1, "DF": defenders, "MF": midfielders, "FW": forwards}


def build(state, **overrides):
    return new_career(
        first_name=overrides.get("first_name", "Avery"),
        last_name=overrides.get("last_name", "Cole"),
        nationality=overrides.get("nationality", "Valland"),
        club_id=overrides.get("club_id", "clb_northbay"),
        difficulty=overrides.get("difficulty", "manager"),
        objective_key=overrides.get("objective", "steady"),
        seed=SEED,
        names_file=None,
    )


class CareerCreationTest(unittest.TestCase):
    def test_user_manager_takes_over_club(self):
        state = build(state=None)
        club = state.user_club()
        self.assertEqual(club.manager_id, state.manager.id)
        self.assertTrue(state.manager.is_user)
        self.assertEqual(state.manager.full_name, "Avery Cole")
        self.assertEqual(state.manager.club_id, state.user_club_id)

    def test_season_opened(self):
        state = build(state=None)
        self.assertIn("2026-27", state.seasons)
        season = state.seasons["2026-27"]
        self.assertFalse(season.finished)
        self.assertEqual(season.current_week, 0)
        self.assertIn("apex_division", season.competition_ids)

    def test_starting_selection_is_legal(self):
        state = build(state=None)
        selection = state.selections[state.user_club_id]
        validate_squad_selection(selection, state.players)

    def test_objectives_from_package(self):
        state = build(state=None, objective="trophy")
        club = state.user_club()
        labels = [o.label for o in club.objectives]
        self.assertTrue(any("top 3" in label for label in labels))
        self.assertTrue(all(o.season == "2026-27" for o in club.objectives))

    def test_unknown_objective_rejected(self):
        with self.assertRaises(CareerError):
            build(state=None, objective="nonsense")

    def test_unknown_club_rejected(self):
        with self.assertRaises(CareerError):
            build(state=None, club_id="clb_ghost")

    def test_empty_manager_name_rejected(self):
        with self.assertRaises(CareerError):
            build(state=None, first_name="   ", last_name="   ")

    def test_difficulty_stored(self):
        state = build(state=None, difficulty="legend")
        self.assertEqual(state.difficulty, Difficulty.LEGEND)


class DifficultyBalanceTest(unittest.TestCase):
    def test_recruit_gives_more_budget_than_legend(self):
        easy = build(state=None, club_id="clb_roma", difficulty="recruit")
        hard = build(state=None, club_id="clb_roma", difficulty="legend")
        self.assertGreater(easy.user_club().finances.transfer_budget,
                         hard.user_club().finances.transfer_budget)


class SaveLoadTest(unittest.TestCase):
    def test_save_and_read_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = build(state=None)
            save_dir = Path(tmp)
            save_new_career(state, save_dir)
            restored = read_save(state.career_id, save_dir)
            self.assertEqual(restored.title, state.title)
            self.assertEqual(restored.difficulty, state.difficulty)
            self.assertEqual(restored.user_club_id, state.user_club_id)
            self.assertEqual(
                restored.selections[restored.user_club_id].starter_ids,
                state.selections[state.user_club_id].starter_ids,
            )
            self.assertEqual(
                restored.players[state.user_club().squad_ids[0]].overall,
                state.players[state.user_club().squad_ids[0]].overall,
            )

    def test_save_list_groups_by_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp)
            state = build(state=None)
            save_new_career(state, save_dir)
            from manager.save.files import list_saves

            entries = list_saves(save_dir)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["title"], state.title)


class BestXiTest(unittest.TestCase):
    def test_all_supported_formations_produce_legal_xi(self):
        state = build(state=None)
        club = state.user_club()
        players = [state.players[pid] for pid in club.squad_ids if pid in state.players]
        for formation in ("4-3-3", "4-4-2", "4-2-3-1", "3-5-2", "5-3-2", "4-3-2-1", "3-4-3", "4-1-4-1"):
            selection = build_best_xi(club.id, players, formation)
            self.assertEqual(len(selection.starter_ids), 11, formation)
            validate_squad_selection(selection, state.players)

    def test_highest_rated_players_in_each_band_start(self):
        state = build(state=None)
        club = state.user_club()
        players = [state.players[pid] for pid in club.squad_ids if pid in state.players]
        selection = build_best_xi(club.id, players)
        starters = {pid for pid in selection.starter_ids}

        by_band = {}
        for player in players:
            band = position_band(player.preferred_position)
            by_band.setdefault(band, []).append(player)

        counts = band_counts("4-3-3")
        for band, needed in counts.items():
            ranked = sorted(by_band[band], key=lambda p: -p.overall)
            for slot in ranked[:needed]:
                self.assertIn(slot.id, starters, f"best {band} should start (got {ranked[:needed]})")


if __name__ == "__main__":
    unittest.main()