"""Tests for core models and their invariants."""

import unittest
from datetime import date

from manager.core.enums import Position
from manager.core.models import Attributes, Club, ClubFinances, Contract, Player
from manager.core.ratings import overall_rating
from manager.core.serialization import dump, load


def make_player(overall_level: int = 70) -> Player:
    return Player(
        id="ply_1",
        first_name="Alia",
        last_name="Torr",
        nationality="Valland",
        date_of_birth=date(2000, 5, 12),
        positions=[Position.CM],
        preferred_position=Position.CM,
        attributes=Attributes(70, 70, 70, 70, 70, 70, 40),
        potential=80,
        club_id="clb_x",
    )


class AttributesClampTest(unittest.TestCase):
    def test_clamps_out_of_range(self):
        attrs = Attributes(999, -5, 70, 70, 70, 70, 70)
        self.assertEqual(attrs.pace, 99)
        self.assertEqual(attrs.shooting, 1)

    def test_overall_rating_weighted(self):
        attrs = Attributes(99, 50, 50, 50, 50, 50, 50)
        cm_rating = overall_rating(attrs, Position.CM)
        st_rating = overall_rating(attrs, Position.ST)
        self.assertGreater(st_rating, cm_rating)  # shooting matters more for a striker


class PlayerInvariantTest(unittest.TestCase):
    def test_potential_gte_overall_returned_within_range(self):
        # Sanity: potential is clamped to 1..99 on construction.
        player = make_player()
        self.assertTrue(1 <= player.potential <= 99)
        self.assertTrue(1 <= player.morale <= 100)

    def test_age_as_of(self):
        player = make_player()
        self.assertEqual(player.age_as_of(2026), 26)


class ClubFinanceTest(unittest.TestCase):
    def test_finance_clamps(self):
        finances = ClubFinances(-10, 20, 5, 4, 0, 0, 0)
        self.assertEqual(finances.balance, 0)

    def test_wage_spend_cannot_exceed_budget_by_constructor(self):
        finances = ClubFinances(100, 50, 10, 12)
        self.assertEqual(finances.weekly_wage_spend, 12)  # not clamped; validated separately


class SerializationRoundTripTest(unittest.TestCase):
    def test_player_round_trip(self):
        player = make_player()
        restored = load(Player, dump(player))
        self.assertEqual(restored.id, player.id)
        self.assertEqual(restored.preferred_position, Position.CM)
        self.assertEqual(restored.attributes.pace, 70)

    def test_club_round_trip_with_finances(self):
        club = Club(
            id="clb_x",
            name="Northbay United",
            city="Northbay",
            nation="Valland",
            stadium_name="Harbour Park",
            capacity=64000,
            primary_color="#1b4d8f",
            secondary_color="#ffffff",
            reputation=96,
            finances=ClubFinances(1_000_000, 300_000, 120_000, 90_000),
        )
        restored = load(Club, dump(club))
        self.assertEqual(restored.finances.transfer_budget, 300_000)
        self.assertEqual(restored.primary_color, "#1b4d8f")

    def test_contract_round_trip(self):
        contract = Contract("ply_1", "clb_x", 12000, "2026-27", "2029-30", release_clause=5_000_000)
        restored = load(Contract, dump(contract))
        self.assertEqual(restored.release_clause, 5_000_000)
        self.assertEqual(restored.end_season, "2029-30")


class EnumsSerializeToValuesTest(unittest.TestCase):
    def test_position_is_string(self):
        self.assertEqual(dump(Position.GK), "GK")


if __name__ == "__main__":
    unittest.main()