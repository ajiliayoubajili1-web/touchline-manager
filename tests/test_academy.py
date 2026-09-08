"""Tests for the academy, scouts and discovery systems."""

import tempfile
import unittest
from pathlib import Path

from manager.api.careers import new_career
from manager.core.models import CareerState
from manager.core.serialization import dump, load
from manager.save.files import read_save, write_save
from manager.systems.scouting import (
    ACADEMY_HARD_CAP,
    ACADEMY_POSITIONS,
    MAX_CONCURRENT_DISCOVERIES,
    MAX_SCOUTS,
    MAX_SQUAD_SIZE,
    ScoutingError,
    academy_roster,
    can_hire_scout,
    demote_to_academy,
    ensure_academies,
    hire_scout,
    process_scouting,
    promote_to_first_team,
    search_now,
    sign_discovery,
)

SEED = 99


def build(**overrides):
    return new_career(
        first_name="Avery",
        last_name="Cole",
        nationality="Valland",
        club_id=overrides.get("club_id", "clb_northbay"),
        difficulty=overrides.get("difficulty", "manager"),
        objective_key=overrides.get("objective", "steady"),
        seed=SEED,
        names_file=None,
    )


def youth_of(state, club_id):
    """Index an academy roster by position."""
    roster = academy_roster(state, club_id)
    by_pos = {}
    for pid in roster:
        player = state.players[pid]
        by_pos[str(player.preferred_position)] = player
    return by_pos


class AcademyRosterTest(unittest.TestCase):
    def test_every_club_has_full_xi(self):
        state = build()
        for club in state.clubs.values():
            self.assertEqual(len(academy_roster(state, club.id)), len(ACADEMY_POSITIONS), club.id)

    def test_academy_players_exist_in_world(self):
        state = build()
        club = state.user_club()
        for pid in academy_roster(state, club.id):
            self.assertIn(pid, state.players)
            self.assertEqual(state.players[pid].club_id, club.id)

    def test_academy_is_idempotent(self):
        state = build()
        before = dict(state.academy)
        ensure_academies(state)
        self.assertEqual(state.academy, before)

    def test_academy_is_a_full_xi(self):
        state = build()
        club = state.user_club()
        roster = academy_roster(state, club.id)
        self.assertEqual(len(roster), len(ACADEMY_POSITIONS))
        by_pos = youth_of(state, club.id)
        self.assertIn("GK", by_pos)


class PromoteDemoteTest(unittest.TestCase):
    def test_promote_moves_to_first_team(self):
        state = build()
        club = state.user_club()
        pid = academy_roster(state, club.id)[0]
        before = len(club.squad_ids)
        promote_to_first_team(state, pid)
        self.assertIn(pid, club.squad_ids)
        self.assertNotIn(pid, academy_roster(state, club.id))
        self.assertEqual(len(club.squad_ids), before + 1)

    def test_promote_fails_when_squad_full(self):
        state = build()
        club = state.user_club()
        club.squad_ids = [f"x_{i}" for i in range(MAX_SQUAD_SIZE)]
        with self.assertRaises(ScoutingError):
            promote_to_first_team(state, academy_roster(state, club.id)[0])

    def test_promote_rejects_unknown_player(self):
        state = build()
        with self.assertRaises(ScoutingError):
            promote_to_first_team(state, "not_here")

    def test_demote_young_player(self):
        state = build()
        club = state.user_club()
        candidate = next(
            state.players[pid] for pid in club.squad_ids
            if state.players[pid].age_as_of(2026) <= 21
        )
        before = len(club.squad_ids)
        demote_to_academy(state, candidate.id)
        self.assertNotIn(candidate.id, club.squad_ids)
        self.assertIn(candidate.id, academy_roster(state, club.id))
        self.assertEqual(len(club.squad_ids), before - 1)

    def test_demote_rejects_older_players(self):
        state = build()
        club = state.user_club()
        older = next(
            state.players[pid] for pid in club.squad_ids
            if state.players[pid].age_as_of(2026) > 21
        )
        with self.assertRaises(ScoutingError):
            demote_to_academy(state, older.id)


class ScoutTest(unittest.TestCase):
    def test_hire_charges_fee_and_deducts_balance(self):
        state = build()
        club = state.user_club()
        balance = club.finances.balance
        scout = hire_scout(state)
        self.assertEqual(len(state.scouts.get(club.id, [])), 1)
        self.assertEqual(scout.weekly_wage, scout.rating * 900)
        self.assertEqual(club.finances.balance, balance - scout.rating * 15_000)

    def test_max_scouts(self):
        state = build()
        for _ in range(MAX_SCOUTS):
            hire_scout(state)
        self.assertFalse(can_hire_scout(state))
        with self.assertRaises(ScoutingError):
            hire_scout(state)

    def test_search_requires_scout(self):
        state = build()
        with self.assertRaises(ScoutingError):
            search_now(state)

    def test_search_discovers_with_scout(self):
        state = build()
        hire_scout(state)
        found = search_now(state)
        self.assertGreaterEqual(len(found), 1)
        club = state.user_club()
        self.assertEqual(len(state.discoveries.get(club.id, [])), len(found))


class DiscoveryTest(unittest.TestCase):
    def _scout_discovering(self):
        state = build()
        scout = hire_scout(state)
        scout.next_discovery_week = state.current_week
        return state, scout

    def test_weekly_process_generates_discovery_and_pays_wage(self):
        state, scout = self._scout_discovering()
        club = state.user_club()
        before = club.finances.balance
        week = state.current_week + 1
        process_scouting(state, week)
        pending = state.discoveries.get(club.id, [])
        self.assertEqual(len(pending), 1)
        discovery = pending[0]
        self.assertEqual(discovery.expires_week, week + 8)
        self.assertGreaterEqual(discovery.signing_fee, 500_000)
        self.assertEqual(club.finances.balance, before - scout.weekly_wage)

    def test_discovery_cap_not_exceeded(self):
        state = build()
        for _ in range(MAX_SCOUTS):
            hire_scout(state)
        for scout in state.scouts[state.user_club().id]:
            scout.next_discovery_week = 1
        club = state.user_club()
        for week in range(1, 60):
            process_scouting(state, week)
            self.assertLessEqual(len(state.discoveries.get(club.id, [])), MAX_CONCURRENT_DISCOVERIES)

    def test_discovery_expires(self):
        state, scout = self._scout_discovering()
        week = state.current_week + 1
        process_scouting(state, week)
        club = state.user_club()
        self.assertEqual(len(state.discoveries.get(club.id, [])), 1)
        state.scouts[club.id][0].next_discovery_week = week + 100
        process_scouting(state, week + 9)
        self.assertEqual(len(state.discoveries.get(club.id, [])), 0)


class SignDiscoveryTest(unittest.TestCase):
    def _with_discovery(self):
        state = build()
        scout = hire_scout(state)
        scout.next_discovery_week = state.current_week
        process_scouting(state, state.current_week + 1)
        return state

    def test_sign_into_academy(self):
        state = self._with_discovery()
        club = state.user_club()
        discovery = state.discoveries[club.id][0]
        budget = club.finances.transfer_budget
        player = sign_discovery(state, discovery.id, "academy")
        self.assertIn(player.id, state.players)
        self.assertIn(player.id, academy_roster(state, club.id))
        self.assertEqual(club.finances.transfer_budget, budget - discovery.signing_fee)
        self.assertEqual(len(state.discoveries[club.id]), 0)

    def test_sign_into_first_team(self):
        state = self._with_discovery()
        club = state.user_club()
        discovery = state.discoveries[club.id][0]
        player = sign_discovery(state, discovery.id, "first_team")
        self.assertIn(player.id, club.squad_ids)

    def test_sign_rejects_poor_budget(self):
        state = self._with_discovery()
        club = state.user_club()
        club.finances.transfer_budget = 0
        discovery = state.discoveries[club.id][0]
        with self.assertRaises(ScoutingError):
            sign_discovery(state, discovery.id, "academy")

    def test_sign_unknown_discovery(self):
        state = self._with_discovery()
        with self.assertRaises(ScoutingError):
            sign_discovery(state, "disc_nope_1_0", "academy")


class SaveCompatibilityTest(unittest.TestCase):
    def test_save_round_trip_preserves_academy_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp)
            state = build()
            club = state.user_club()
            scout = hire_scout(state)
            scout.next_discovery_week = state.current_week
            process_scouting(state, state.current_week + 1)
            write_save(state, save_dir)
            loaded = read_save(state.career_id, save_dir)
            self.assertEqual(len(loaded.academy[club.id]), len(ACADEMY_POSITIONS))
            self.assertEqual(len(loaded.scouts[club.id]), 1)
            self.assertEqual(loaded.scouts[club.id][0].full_name, scout.full_name)
            self.assertEqual(len(loaded.discoveries[club.id]), 1)
            self.assertEqual(loaded.discoveries[club.id][0].id, state.discoveries[club.id][0].id)

    def test_old_saves_migrate_academy(self):
        state = build()
        payload = dump(state)
        for key in ("academy", "scouts", "discoveries"):
            payload.pop(key, None)
        migrated = load(CareerState, payload)
        self.assertEqual(migrated.academy, {})
        ensure_academies(migrated)
        for club in migrated.clubs.values():
            self.assertEqual(len(academy_roster(migrated, club.id)), len(ACADEMY_POSITIONS))

    def test_rollover_promotes_from_academy_first(self):
        state = build()
        club = state.user_club()
        state.seasons[state.current_season].finished = True
        state.current_week = state.seasons[state.current_season].total_weeks

        del club.squad_ids[20:]
        self.assertEqual(len(club.squad_ids), 20)
        roster_before = len(academy_roster(state, club.id))

        from manager.systems.season import start_next_season

        start_next_season(state)
        self.assertEqual(len(club.squad_ids), 25)
        self.assertLessEqual(len(academy_roster(state, club.id)), roster_before - 5)


if __name__ == "__main__":
    unittest.main()