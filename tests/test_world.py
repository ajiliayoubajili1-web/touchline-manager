"""Tests for the fictional world database generator."""

import unittest

from manager.core.enums import Position
from manager.core.models import Manager
from manager.core.validate import validate_player
from manager.data.world import build_world


class WorldDatabaseTest(unittest.TestCase):
    def test_deterministic_world(self):
        a = build_world(seed=123)
        b = build_world(seed=123)
        self.assertEqual([c.id for c in a.clubs], [c.id for c in b.clubs])
        names = sorted((p.id, p.overall) for p in a.players)
        names_b = sorted((p.id, p.overall) for p in b.players)
        self.assertEqual(names, names_b)

    def test_clubs_and_competitions_present(self):
        world = build_world(seed=7)
        self.assertGreaterEqual(len(world.clubs), 18)
        self.assertEqual(len(world.competitions), 2)
        apex = next(c for c in world.competitions if c.id == "apex_division")
        self.assertEqual(len(apex.club_ids), len(world.clubs))
        self.assertEqual(apex.params["rounds"], 2 * (len(world.clubs) - 1))

    def test_each_club_has_full_squad(self):
        world = build_world(seed=7)
        for club in world.clubs:
            squad = [p for p in world.players if p.club_id == club.id]
            self.assertEqual(len(squad), 25, f"{club.name} should have a 25-man squad")
            self.assertEqual(set(club.squad_ids), {p.id for p in squad})

    def test_squad_has_one_goalkeeper_profile_balanced(self):
        world = build_world(seed=7)
        for club in world.clubs:
            squad = [p for p in world.players if p.club_id == club.id]
            self.assertGreaterEqual(
                sum(1 for p in squad if Position.GK in p.positions), 1,
                f"{club.name} needs a goalkeeper",
            )

    def test_player_validity(self):
        world = build_world(seed=7)
        for player in world.players:
            if not hasattr(player, "attributes"):
                continue
            validate_player(player)

    def test_free_agents_have_no_club(self):
        world = build_world(seed=7)
        free = [p for p in world.players if p.club_id is None and hasattr(p, "attributes")]
        self.assertGreaterEqual(len(free), 40)

    def test_managers_created_and_assigned(self):
        world = build_world(seed=7)
        managers = world.managers
        self.assertTrue(all(isinstance(m, Manager) for m in managers))
        club_ids = {c.id for c in world.clubs}
        self.assertEqual({m.club_id for m in managers}, club_ids)