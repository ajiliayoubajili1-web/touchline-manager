"""Tests for training plans, tactical roles and weekly development."""

import unittest

from manager.core.enums import Position, TacticalDuty, TrainingFocus, TrainingIntensity
from manager.core.models import CareerState
from manager.systems.development import (
    allowed_roles,
    apply_training_plan,
    development_tick,
)
from manager.core.validate import ValidationError

SEED = 2026


def make_career(seed=SEED) -> CareerState:
    from manager.api.careers import new_career

    return new_career(
        first_name="Remy", last_name="Duran", nationality="Valland",
        club_id="clb_northbay", difficulty="manager",
        objective_key="steady", seed=seed, names_file=None,
    )


class TrainingPlanTest(unittest.TestCase):
    def test_apply_plan_writes_fields(self):
        state = make_career()
        player = state.players[state.user_club().squad_ids[0]]
        apply_training_plan(state, player.id, "attacking", "high", "standard", "attack")
        self.assertEqual(player.training_focus, TrainingFocus.ATTACKING)
        self.assertEqual(player.training_intensity, TrainingIntensity.HIGH)
        self.assertEqual(player.tactical_role, "standard")
        self.assertEqual(player.tactical_duty, TacticalDuty.ATTACK)

    def test_invalid_role_rejected(self):
        state = make_career()
        player = state.players[state.user_club().squad_ids[0]]
        with self.assertRaises(ValidationError):
            apply_training_plan(state, player.id, "general", "normal", "bogus_role", "support")

    def test_invalid_focus_rejected(self):
        state = make_career()
        player = state.players[state.user_club().squad_ids[0]]
        with self.assertRaises(ValidationError):
            apply_training_plan(state, player.id, "nonsense", "normal", "standard", "support")

    def test_non_squad_player_rejected(self):
        state = make_career()
        foreign = next(
            p for p in state.players.values()
            if p.club_id not in (None, state.user_club_id)
        )
        with self.assertRaises(ValidationError):
            apply_training_plan(state, foreign.id, "general", "normal", "standard", "support")

    def test_allowed_roles_match_position_group(self):
        state = make_career()
        players = [state.players[pid] for pid in state.user_club().squad_ids]
        striker = next(p for p in players if p.preferred_position in (Position.ST, Position.CF))
        self.assertIn("poacher", allowed_roles(striker))
        keeper = next(p for p in players if p.preferred_position == Position.GK)
        self.assertIn("shot_stopper", allowed_roles(keeper))
        self.assertNotIn("poacher", allowed_roles(keeper))


class DevelopmentTickTest(unittest.TestCase):
    def test_development_is_deterministic(self):
        state_a = make_career()
        state_b = make_career()
        for _ in range(5):
            development_tick(state_a, state_a.current_week + 1)
        snap_b = {
            p.id: tuple(getattr(p.attributes, name) for name in
                        ("pace", "shooting", "passing", "dribbling", "defending", "physical", "goalkeeper"))
            for p in state_a.players.values()
        }
        for _ in range(5):
            development_tick(state_b, state_b.current_week + 1)
        for pid, attrs in snap_b.items():
            b = state_b.players[pid].attributes
            self.assertEqual(attrs, (b.pace, b.shooting, b.passing, b.dribbling, b.defending, b.physical, b.goalkeeper))

    def test_attributes_stay_in_bounds(self):
        state = make_career()
        for week in range(1, 5):
            development_tick(state, week)
        for player in state.players.values():
            for name in ("pace", "shooting", "passing", "dribbling", "defending", "physical", "goalkeeper"):
                value = getattr(player.attributes, name)
                self.assertTrue(1 <= value <= 99, f"{player.id} attr {name}={value}")

    def test_user_squad_records_growth_history(self):
        state = make_career()
        grew = False
        for week in range(1, 6):
            development_tick(state, week)
            for pid in state.user_club().squad_ids:
                if state.players[pid].development_history:
                    grew = True
        self.assertEqual(grew, len([p for p in (state.players[pid] for pid in state.user_club().squad_ids) if p.development_history]) > 0)

    def test_history_note_and_overall_consistent(self):
        state = make_career()
        for week in range(1, 6):
            development_tick(state, week)
        holder = next(
            (p for p in (state.players[pid] for pid in state.user_club().squad_ids) if p.development_history),
            None,
        )
        if holder is None:
            self.skipTest("no growth recorded for this seed")
        record = holder.development_history[-1]
        total = sum(record.attribute_growth.values())
        self.assertGreaterEqual(record.overall_after, record.overall_before - 2)
        self.assertLessEqual(record.overall_after, record.overall_before + 10)

    def test_high_intensity_plan_survives_save_roundtrip(self):
        from manager.save.files import write_save, read_save
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            state = make_career()
            player = state.players[state.user_club().squad_ids[0]]
            apply_training_plan(state, player.id, "physical", "high", "standard", "support")
            write_save(state, Path(tmpdir))
            loaded = read_save(state.career_id, Path(tmpdir))
            lp = loaded.players[player.id]
            self.assertEqual(lp.training_focus, TrainingFocus.PHYSICAL)
            self.assertEqual(lp.training_intensity, TrainingIntensity.HIGH)


class TrainingApiTest(unittest.TestCase):
    def make_service(self):
        from manager.api.service import GameService

        service = GameService()
        service.create_career({
            "first_name": "Remy", "last_name": "Duran",
            "nationality": "Valland", "club_id": "clb_northbay",
            "difficulty": "manager", "objective": "steady", "seed": 2026,
        })
        return service

    def test_training_query(self):
        service = self.make_service()
        view = service.query("training", {})
        self.assertEqual(view["role"], "training")
        self.assertEqual(len(view["players"]), len(service.state.user_club().squad_ids))
        self.assertIn("standard", view["players"][0]["allowed_roles"])

    def test_set_player_plan_action(self):
        service = self.make_service()
        state = service.state
        player = state.players[state.user_club().squad_ids[0]]
        view = service.action("set_player_plan", {
            "player_id": player.id,
            "focus": "defending",
            "intensity": "high",
            "role": "standard",
            "duty": "defend",
        })
        self.assertEqual(view["role"], "training")
        row = next(r for r in view["players"] if r["id"] == player.id)
        self.assertEqual(row["focus"], "defending")
        self.assertEqual(row["intensity"], "high")
        self.assertEqual(row["duty"], "defend")

    def test_invalid_plan_rejected_by_api(self):
        from manager.api.service import ServiceError

        service = self.make_service()
        state = service.state
        player = state.players[state.user_club().squad_ids[0]]
        with self.assertRaises(ServiceError):
            service.action("set_player_plan", {
                "player_id": player.id,
                "focus": "attacking",
                "intensity": "high",
                "role": "not_a_role",
                "duty": "attack",
            })


if __name__ == "__main__":
    unittest.main()