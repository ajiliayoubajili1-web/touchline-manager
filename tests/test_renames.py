"""Tests for the editable custom-names system."""

import json
import tempfile
import unittest
from pathlib import Path

from manager.data.renames import NameOverrides, apply_custom_names, load_custom_names
from manager.data.world import build_world


class LoadCustomNamesTest(unittest.TestCase):
    def test_missing_file_yields_empty(self):
        overrides = load_custom_names("does_not_exist.json")
        self.assertTrue(overrides.empty)
        self.assertEqual(overrides.warnings, [])

    def test_invalid_json_yields_warning(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write("{ not json")
            path = handle.name
        try:
            overrides = load_custom_names(path)
            self.assertTrue(overrides.empty)
            self.assertEqual(len(overrides.warnings), 1)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_doc_keys_ignored(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"_doc": "hello", "clubs": {"northbay": "BARCA"}}, handle)
            path = handle.name
        try:
            overrides = load_custom_names(path)
            self.assertEqual(overrides.clubs, {"northbay": "BARCA"})
        finally:
            Path(path).unlink(missing_ok=True)

    def test_invalid_entry_types_warned(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"clubs": {"northbay": 123}}, handle)
            path = handle.name
        try:
            overrides = load_custom_names(path)
            self.assertEqual(overrides.clubs, {})
            self.assertEqual(len(overrides.warnings), 1)
        finally:
            Path(path).unlink(missing_ok=True)


class ApplyCustomNamesTest(unittest.TestCase):
    def test_rename_club_and_player(self):
        world = build_world(seed=11)
        northbay = next(c for c in world.clubs if c.id == "clb_northbay")
        player = next(p for p in world.players if p.id == "clb_northbay_03")

        overrides = NameOverrides(
            clubs={"northbay": "BARCA"},
            players={"northbay.03": {"first_name": "MISSI", "last_name": "I"}},
        )
        warnings = apply_custom_names(world, overrides)
        self.assertEqual(warnings, [])
        self.assertEqual(northbay.name, "BARCA")
        self.assertEqual(player.first_name, "MISSI")
        self.assertEqual(player.last_name, "I")

    def test_unknown_keys_warned(self):
        world = build_world(seed=11)
        overrides = NameOverrides(clubs={"ghosttown": "X"}, players={"ghost.99": "Y"})
        warnings = apply_custom_names(world, overrides)
        self.assertEqual(len(warnings), 2)

    def test_full_name_string_replaces_both_parts(self):
        world = build_world(seed=11)
        player = next(p for p in world.players if p.id == "clb_northbay_03")
        overrides = NameOverrides(players={"clb_northbay_03": "MISSI"})
        apply_custom_names(world, overrides)
        self.assertEqual(player.full_name, "MISSI")

    def test_build_world_applies_name_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"clubs": {"northbay": "BARCA"}}, handle)
            path = handle.name
        try:
            world = build_world(seed=11, names_file=path)
            northbay = next(c for c in world.clubs if c.id == "clb_northbay")
            self.assertEqual(northbay.name, "BARCA")
        finally:
            Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()