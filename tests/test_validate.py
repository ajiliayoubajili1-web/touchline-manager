"""Tests for validation rules."""

import unittest
from datetime import date

from manager.core.enums import Position
from manager.core.models import Attributes, Player, SquadSelection, Tactics
from manager.core.validate import (
    ValidationError,
    validate_squad_selection,
    validate_tactics,
    validate_transfer_affordability,
    validate_transfer_params,
    parse_formation,
)
from manager.core.models import Club, ClubFinances


class FormationTest(unittest.TestCase):
    def test_parse_valid(self):
        self.assertEqual(parse_formation("4-3-3"), (4, 3, 3))
        self.assertEqual(parse_formation("3-5-2"), (3, 5, 2))
        self.assertEqual(parse_formation("4-2-3-1"), (4, 2 + 3, 1))
        self.assertEqual(parse_formation("4-1-4-1"), (4, 1 + 4, 1))

    def test_invalid_formation(self):
        for bad in ("", "4-3", "9-1-0", "4-4-3", "abc", "11-0-0"):
            with self.assertRaises(ValidationError):
                validate_tactics(Tactics(formation=bad))

    def test_valid_formation_passes(self):
        validate_tactics(Tactics(formation="4-3-3"))


def build_players():
    players = {}
    for i, position in enumerate([Position.GK, Position.CB, Position.CB, Position.CB, Position.CB,
                                  Position.CM, Position.CM, Position.CM, Position.LW, Position.RW, Position.ST]):
        player = Player(
            id=f"p{i}",
            first_name="F",
            last_name=str(i),
            nationality="Valland",
            date_of_birth=date(2000, 1, 1),
            positions=[position],
            preferred_position=position,
            attributes=Attributes(60, 60, 60, 60, 60, 60, 60),
            potential=70,
            club_id="clb_from",
        )
        players[player.id] = player
    return players


class SquadSelectionTest(unittest.TestCase):
    def test_valid_xi_passes(self):
        players = build_players()
        selection = SquadSelection(club_id="clb_from", starter_ids=list(players.keys()))
        validate_squad_selection(selection, players)

    def test_requires_eleven(self):
        players = build_players()
        ids = list(players.keys())[:10]
        selection = SquadSelection(club_id="clb_from", starter_ids=ids)
        with self.assertRaises(ValidationError):
            validate_squad_selection(selection, players)

    def test_requires_one_goalkeeper(self):
        players = build_players()
        ids = list(players.keys())
        # replace the keeper with an outfield player
        ids[0] = "p1"
        selection = SquadSelection(club_id="clb_from", starter_ids=ids)
        with self.assertRaises(ValidationError):
            validate_squad_selection(selection, players)

    def test_player_from_other_club_rejected(self):
        players = build_players()
        players["p0"].club_id = "clb_other"
        selection = SquadSelection(club_id="clb_from", starter_ids=list(players.keys()))
        with self.assertRaises(ValidationError):
            validate_squad_selection(selection, players)

    def test_duplicate_player_rejected(self):
        players = build_players()
        ids = list(players.keys())
        ids[1] = ids[0]
        selection = SquadSelection(club_id="clb_from", starter_ids=ids)
        with self.assertRaises(ValidationError):
            validate_squad_selection(selection, players)


class TransferValidationTest(unittest.TestCase):
    def test_invalid_params(self):
        with self.assertRaises(ValidationError):
            validate_transfer_params(-5, 1000, 3)
        with self.assertRaises(ValidationError):
            validate_transfer_params(100, -1, 3)
        with self.assertRaises(ValidationError):
            validate_transfer_params(100, 1000, 0)

    def test_affordability(self):
        club = Club(
            id="clb_x", name="X", city="C", nation="Valland", stadium_name="S",
            capacity=100, primary_color="#000", secondary_color="#fff", reputation=50,
            finances=ClubFinances(balance=10, transfer_budget=1000, weekly_wage_budget=500, weekly_wage_spend=400),
        )
        validate_transfer_affordability(club, fee=900, weekly_wage=90)
        with self.assertRaises(ValidationError):
            validate_transfer_affordability(club, fee=1100, weekly_wage=90)
        with self.assertRaises(ValidationError):
            validate_transfer_affordability(club, fee=100, weekly_wage=200)  # wage over remaining 100


class AttributeValidationTest(unittest.TestCase):
    def test_unknown_attribute_rejected(self):
        from manager.core.validate import validate_attribute_value
        with self.assertRaises(ValidationError):
            validate_attribute_value("cheese", 50)


if __name__ == "__main__":
    unittest.main()