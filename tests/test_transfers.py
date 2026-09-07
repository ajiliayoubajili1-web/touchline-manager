"""Tests for transfers, contracts and budget spending."""

import unittest

from manager.core.enums import NewsCategory, TransferStatus, TransferType
from manager.core.models import CareerState
from manager.systems.transfers import (
    LOAN_MAX,
    TransferError,
    loan_eligible,
    loan_out_player,
    propose_loan,
    propose_transfer,
    renew_contract,
    return_loans,
    sell_player,
)

SEED = 2026


def make_career(seed=SEED) -> CareerState:
    from manager.api.careers import new_career

    return new_career(
        first_name="Remy", last_name="Duran", nationality="Valland",
        club_id="clb_northbay", difficulty="manager",
        objective_key="steady", seed=seed, names_file=None,
    )


def owned_target(state: CareerState, club_id: str, ceiling: int = 3_000_000):
    """Cheapest AI-owned player we can bid on (deterministic for a seed)."""
    candidates = [
        p for p in state.players.values()
        if p.club_id is not None and p.club_id != club_id and p.valuation <= ceiling
    ]
    return min(candidates, key=lambda p: p.valuation)


def free_target(state: CareerState):
    candidates = [p for p in state.players.values() if p.club_id is None]
    return max(candidates, key=lambda p: p.overall)


def loan_target(state: CareerState):
    """Cheapest AI player a club would let go on loan (deterministic for a seed)."""
    candidates = [
        p for p in state.players.values()
        if p.club_id is not None and p.club_id != state.user_club_id and loan_eligible(state, p)
    ]
    return max(candidates, key=lambda p: -p.overall)


class TransferSystemTest(unittest.TestCase):
    def test_generous_bid_is_accepted(self):
        state = make_career()
        club = state.user_club()
        target = owned_target(state, club.id)
        buyer = club.id
        seller = target.club_id
        budget_before = club.finances.transfer_budget
        seller_budget_before = state.club(seller).finances.transfer_budget

        fee = int(target.valuation * 3)
        wage = (target.contract.weekly_wage if target.contract else 1000) + 2000
        result = propose_transfer(state, target.id, fee, wage, 3)

        self.assertTrue(result["accepted"])
        self.assertEqual(state.players[target.id].club_id, buyer)
        self.assertEqual(state.players[target.id].contract.club_id, buyer)
        self.assertEqual(state.players[target.id].contract.end_season, "2029-30")
        self.assertEqual(club.finances.transfer_budget, budget_before - fee)
        self.assertEqual(state.club(seller).finances.transfer_budget, seller_budget_before + fee)
        self.assertIn(target.id, club.squad_ids)
        self.assertNotIn(target.id, state.club(seller).squad_ids)
        transfer = state.transfers[-1]
        self.assertEqual(transfer.status, TransferStatus.COMPLETED)
        self.assertEqual(transfer.transfer_type, TransferType.PERMANENT)
        self.assertEqual(transfer.fee, fee)
        self.assertEqual(state.news[-1].category, NewsCategory.TRANSFER_DONE)

    def test_tiny_bid_is_rejected_and_state_unchanged(self):
        state = make_career()
        club = state.user_club()
        target = owned_target(state, club.id)
        seller = target.club_id
        budget_before = club.finances.transfer_budget
        wage_before = (target.contract.weekly_wage if target.contract else 0) + 1000

        result = propose_transfer(state, target.id, 0, wage_before, 3)

        self.assertFalse(result["accepted"])
        self.assertEqual(state.players[target.id].club_id, seller)
        self.assertEqual(club.finances.transfer_budget, budget_before)
        self.assertEqual(state.transfers[-1].status, TransferStatus.DECLINED)
        self.assertEqual(state.news[-1].category, NewsCategory.TRANSFER_RUMOR)

    def test_free_agent_signs_directly_no_fee(self):
        state = make_career()
        club = state.user_club()
        target = free_target(state)

        result = propose_transfer(state, target.id, 0, 15000, 2)

        self.assertTrue(result["accepted"])
        self.assertEqual(result["kind"], "free")
        self.assertEqual(state.players[target.id].club_id, club.id)
        self.assertGreater(club.finances.weekly_wage_spend, 0)
        self.assertEqual(state.transfers[-1].transfer_type, TransferType.FREE)

    def test_free_agent_fee_is_forced_to_zero(self):
        state = make_career()
        club = state.user_club()
        target = free_target(state)
        budget_before = club.finances.transfer_budget

        result = propose_transfer(state, target.id, 2_000_000, 15000, 2)

        self.assertTrue(result["accepted"])
        self.assertEqual(state.transfers[-1].fee, 0)
        self.assertEqual(club.finances.transfer_budget, budget_before)

    def test_cannot_buy_own_player(self):
        state = make_career()
        club = state.user_club()
        own = state.players[club.squad_ids[0]]
        with self.assertRaises(TransferError):
            propose_transfer(state, own.id, 10_000_000, 50_000, 3)

    def test_fee_over_budget_is_rejected(self):
        state = make_career()
        club = state.user_club()
        target = owned_target(state, club.id)
        with self.assertRaises(TransferError):
            propose_transfer(state, target.id, 999_999_999, 50_000, 3)

    def test_wage_over_room_is_rejected(self):
        state = make_career()
        club = state.user_club()
        target = owned_target(state, club.id)
        with self.assertRaises(TransferError):
            propose_transfer(state, target.id, 0, 10_000_000, 3)

    def test_idempotent_acceptance_for_same_seed(self):
        state_a = make_career()
        state_b = make_career()
        club_a = state_a.user_club()
        club_b = state_b.user_club()
        ta = owned_target(state_a, club_a.id)
        tb = state_b.players[ta.id]

        ra = propose_transfer(state_a, ta.id, int(ta.valuation * 3), 50_000, 3)
        rb = propose_transfer(state_b, tb.id, int(tb.valuation * 3), 50_000, 3)
        self.assertEqual(ra["accepted"], rb["accepted"])

    def test_renew_contract_extends_and_raises_wage(self):
        state = make_career()
        club = state.user_club()
        player = state.players[club.squad_ids[0]]
        old = player.contract.weekly_wage
        old_end = player.contract.end_season
        spend_before = club.finances.weekly_wage_spend

        result = renew_contract(state, player.id, old + 2000, 4)

        self.assertTrue(result["renewed"])
        self.assertEqual(player.contract.weekly_wage, old + 2000)
        self.assertEqual(player.contract.end_season, "2030-31")
        self.assertNotEqual(player.contract.end_season, old_end)
        self.assertEqual(club.finances.weekly_wage_spend, spend_before + 2000)
        self.assertEqual(state.news[-1].category, NewsCategory.CONTRACT)

    def test_sell_player_adds_budget_and_frees_player(self):
        state = make_career()
        club = state.user_club()
        player = state.players[club.squad_ids[1]]
        budget_before = club.finances.transfer_budget
        wage_before = player.contract.weekly_wage
        spend_before = club.finances.weekly_wage_spend
        fee = int(player.valuation * 0.9)

        result = sell_player(state, player.id, fee)

        self.assertTrue(result["sold"])
        self.assertEqual(club.finances.transfer_budget, budget_before + fee)
        self.assertEqual(club.finances.weekly_wage_spend, spend_before - wage_before)
        self.assertNotIn(player.id, club.squad_ids)
        self.assertIsNone(state.players[player.id].club_id)
        self.assertIsNone(state.players[player.id].contract)

    def test_sell_player_low_fee_is_rejected(self):
        state = make_career()
        club = state.user_club()
        player = state.players[club.squad_ids[2]]
        with self.assertRaises(TransferError):
            sell_player(state, player.id, 1000)

    def test_loan_in_moves_player_and_wages(self):
        state = make_career()
        club = state.user_club()
        target = loan_target(state)
        donor_id = target.club_id
        donor = state.club(donor_id)
        wage = target.contract.weekly_wage
        spend_before = club.finances.weekly_wage_spend
        donor_spend_before = donor.finances.weekly_wage_spend
        contract_club_before = target.contract.club_id

        result = propose_loan(state, target.id)

        self.assertTrue(result["accepted"])
        self.assertEqual(result["kind"], "loan")
        self.assertEqual(state.players[target.id].club_id, club.id)
        self.assertEqual(state.players[target.id].loaned_from, donor_id)
        self.assertIn(target.id, club.squad_ids)
        self.assertNotIn(target.id, donor.squad_ids)
        self.assertEqual(club.finances.weekly_wage_spend, spend_before + wage)
        self.assertEqual(donor.finances.weekly_wage_spend, donor_spend_before - wage)
        self.assertEqual(state.players[target.id].contract.club_id, contract_club_before)
        record = state.transfers[-1]
        self.assertEqual(record.transfer_type, TransferType.LOAN)
        self.assertEqual(record.fee, 0)
        self.assertEqual(record.status, TransferStatus.COMPLETED)

    def test_loaned_in_player_cannot_be_renewed_or_sold(self):
        state = make_career()
        club = state.user_club()
        target = loan_target(state)
        propose_loan(state, target.id)
        with self.assertRaises(TransferError):
            renew_contract(state, target.id, 50_000, 3)
        with self.assertRaises(TransferError):
            sell_player(state, target.id, 1_000_000)

    def test_loan_out_of_fringe_player_finds_host(self):
        state = make_career()
        club = state.user_club()
        fringe = min(
            (p for pid in club.squad_ids if (p := state.players.get(pid)) is not None
             and p.loaned_from is None and p.overall <= 60),
            key=lambda p: p.overall,
        )
        host_wage_before = state.club(state.user_club().id).finances.weekly_wage_spend
        usage = len(club.squad_ids)

        result = loan_out_player(state, fringe.id)

        self.assertTrue(result["accepted"])
        self.assertNotIn(fringe.id, club.squad_ids)
        self.assertEqual(state.players[fringe.id].loaned_from, club.id)
        self.assertEqual(state.players[fringe.id].club_id, result["host_id"])
        self.assertEqual(len(club.squad_ids), usage - 1)
        wage = state.players[fringe.id].contract.weekly_wage if state.players[fringe.id].contract else 0
        self.assertEqual(club.finances.weekly_wage_spend, host_wage_before - wage)
        self.assertIn(fringe.id, state.club(result["host_id"]).squad_ids)

    def test_loan_out_of_starter_is_rejected(self):
        state = make_career()
        club = state.user_club()
        starter = state.players[state.selections[club.id].starter_ids[0]]
        with self.assertRaises(TransferError):
            loan_out_player(state, starter.id)

    def test_loan_cap_is_enforced(self):
        state = make_career()
        taken = set()
        for _ in range(LOAN_MAX):
            target = next(
                p for p in state.players.values()
                if p.club_id is not None and p.id not in taken
                and loan_eligible(state, p)
            )
            taken.add(target.id)
            propose_loan(state, target.id)
        spare = next(
            p for p in state.players.values()
            if p.club_id is not None and p.id not in taken and loan_eligible(state, p)
        )
        with self.assertRaises(TransferError):
            propose_loan(state, spare.id)

    def test_loans_return_at_season_end(self):
        from manager.systems.match import simulate_season
        from manager.systems.season import start_next_season

        state = make_career()
        club = state.user_club()
        target = loan_target(state)
        donor_id = target.club_id
        propose_loan(state, target.id)

        simulate_season(state)
        start_next_season(state)

        player = state.players[target.id]
        self.assertIsNone(player.loaned_from)
        self.assertEqual(player.club_id, donor_id)
        self.assertIn(player.id, state.club(donor_id).squad_ids)
        self.assertNotIn(player.id, club.squad_ids)

    # ---- transfer windows + incoming offers ----

    def _advance_to_week(self, state, week):
        from manager.systems.match import simulate_to_week

        simulate_to_week(state, week)

    def test_summer_window_open_at_week_zero(self):
        from manager.systems.transfers import transfer_window

        state = make_career()
        self.assertTrue(transfer_window(state)["open"])
        self.assertEqual(transfer_window(state)["name"], "summer")

    def test_window_closed_outside_summer(self):
        from manager.systems.transfers import transfer_window

        state = make_career()
        self._advance_to_week(state, 6)
        self.assertFalse(transfer_window(state)["open"])
        self.assertEqual(transfer_window(state)["name"], "closed")

    def test_winter_window_open_at_midpoint(self):
        from manager.systems.transfers import transfer_window

        state = make_career()
        season = state.seasons[state.current_season]
        mid = season.total_weeks // 2
        self._advance_to_week(state, mid)
        self.assertTrue(transfer_window(state)["open"])
        self.assertEqual(transfer_window(state)["name"], "winter")

    def test_buying_blocked_outside_window(self):
        from manager.systems.transfers import propose_transfer

        state = make_career()
        self._advance_to_week(state, 6)
        target = owned_target(state, state.user_club_id)
        fee = int(target.valuation * 3)
        wage = (target.contract.weekly_wage if target.contract else 1000) + 2000
        with self.assertRaises(TransferError):
            propose_transfer(state, target.id, fee, wage, 3)

    def test_free_agent_signable_outside_window(self):
        from manager.systems.transfers import propose_transfer, transfer_window

        state = make_career()
        self._advance_to_week(state, 6)
        self.assertFalse(transfer_window(state)["open"])
        target = free_target(state)
        self.assertIsNone(target.club_id)
        budget_before = state.user_club().finances.transfer_budget

        result = propose_transfer(state, target.id, 0, 2000, 3)

        self.assertTrue(result["accepted"])
        self.assertEqual(result["kind"], "free")
        self.assertEqual(state.players[target.id].club_id, state.user_club_id)
        self.assertEqual(state.user_club().finances.transfer_budget, budget_before)
        self.assertEqual(state.transfers[-1].fee, 0)

    def test_offers_generated_for_user_squad(self):
        from manager.systems.transfers import _generate_incoming_offers

        state = make_career()
        _generate_incoming_offers(state)
        pending = [o for o in state.incoming_offers if o.status == "pending"]
        self.assertGreater(len(pending), 0)
        for offer in pending:
            self.assertEqual(state.players[offer.player_id].club_id, state.user_club_id)
            self.assertNotEqual(offer.buyer_club_id, state.user_club_id)
            self.assertGreater(offer.fee, 0)

    def test_accept_offer_completes_sale(self):
        from manager.systems.transfers import _generate_incoming_offers, accept_offer

        state = make_career()
        _generate_incoming_offers(state)
        offer = next(o for o in state.incoming_offers if o.status == "pending")
        club = state.user_club()
        player = state.players[offer.player_id]
        buyer = state.clubs[offer.buyer_club_id]
        budget_before = club.finances.transfer_budget

        result = accept_offer(state, offer.id)

        self.assertTrue(result["accepted"])
        self.assertEqual(state.players[player.id].club_id, buyer.id)
        self.assertIn(player.id, buyer.squad_ids)
        self.assertNotIn(player.id, club.squad_ids)
        self.assertEqual(club.finances.transfer_budget, budget_before + offer.fee)
        self.assertEqual(next(o for o in state.incoming_offers if o.id == offer.id).status, "accepted")

    def test_accept_offer_withdraws_duplicate_pending(self):
        from manager.systems.transfers import _generate_incoming_offers, accept_offer

        state = make_career()
        _generate_incoming_offers(state)
        offer = next(o for o in state.incoming_offers if o.status == "pending")
        duplicate = [o for o in state.incoming_offers if o.player_id == offer.player_id and o.id != offer.id]
        accept_offer(state, offer.id)
        for other in duplicate:
            self.assertIn(other.status, ("withdrawn", "accepted", "refused"))

    def test_refuse_offer_keeps_player(self):
        from manager.systems.transfers import _generate_incoming_offers, refuse_offer

        state = make_career()
        _generate_incoming_offers(state)
        offer = next(o for o in state.incoming_offers if o.status == "pending")
        player_id = offer.player_id
        club = state.user_club()

        result = refuse_offer(state, offer.id)

        self.assertTrue(result["refused"])
        self.assertEqual(state.players[player_id].club_id, club.id)
        self.assertIn(player_id, club.squad_ids)
        self.assertEqual(next(o for o in state.incoming_offers if o.id == offer.id).status, "refused")

    def test_accept_already_resolved_offer_rejected(self):
        from manager.systems.transfers import _generate_incoming_offers, refuse_offer, TransferError, accept_offer

        state = make_career()
        _generate_incoming_offers(state)
        offer = next(o for o in state.incoming_offers if o.status == "pending")
        refuse_offer(state, offer.id)
        with self.assertRaises(TransferError):
            accept_offer(state, offer.id)

    def test_negotiate_offer_at_lower_fee_always_accepted(self):
        from manager.systems.transfers import _generate_incoming_offers, negotiate_offer

        state = make_career()
        _generate_incoming_offers(state)
        offer = next(o for o in state.incoming_offers if o.status == "pending")
        club = state.user_club()
        buyer = state.clubs[offer.buyer_club_id]
        budget_before = club.finances.transfer_budget
        counter = offer.fee // 2

        result = negotiate_offer(state, offer.id, counter)

        self.assertTrue(result["accepted"])
        self.assertEqual(state.players[offer.player_id].club_id, buyer.id)
        self.assertEqual(club.finances.transfer_budget, budget_before + counter)
        self.assertEqual(next(o for o in state.incoming_offers if o.id == offer.id).status, "accepted")

    def test_negotiate_offer_greedy_counter_walks_away(self):
        from manager.systems.transfers import _generate_incoming_offers, negotiate_offer

        state = make_career()
        _generate_incoming_offers(state)
        offer = next(o for o in state.incoming_offers if o.status == "pending")
        player_id = offer.player_id
        club = state.user_club()

        result = negotiate_offer(state, offer.id, int(offer.fee * 3))

        self.assertFalse(result["accepted"])
        self.assertEqual(state.players[player_id].club_id, club.id)
        self.assertIn(player_id, club.squad_ids)
        self.assertEqual(next(o for o in state.incoming_offers if o.id == offer.id).status, "withdrawn")

    def test_negotiate_offer_unrealistic_counter_walks_away(self):
        from manager.systems.transfers import _generate_incoming_offers, negotiate_offer

        state = make_career()
        _generate_incoming_offers(state)
        offer = next(o for o in state.incoming_offers if o.status == "pending")
        result = negotiate_offer(state, offer.id, int(state.players[offer.player_id].valuation * 4))
        self.assertFalse(result["accepted"])
        self.assertEqual(next(o for o in state.incoming_offers if o.id == offer.id).status, "withdrawn")

    def test_negotiate_blocked_outside_window(self):
        from manager.systems.transfers import _generate_incoming_offers, negotiate_offer, TransferError

        state = make_career()
        _generate_incoming_offers(state)
        offer = next(o for o in state.incoming_offers if o.status == "pending")
        self._advance_to_week(state, 6)
        with self.assertRaises(TransferError):
            negotiate_offer(state, offer.id, offer.fee)


class TransferApiTest(unittest.TestCase):
    def make_service(self):
        from manager.api.service import GameService

        service = GameService()
        service.create_career({
            "first_name": "Remy", "last_name": "Duran",
            "nationality": "Valland", "club_id": "clb_northbay",
            "difficulty": "manager", "objective": "steady", "seed": 2026,
        })
        return service

    def test_market_query_returns_targets_and_budget(self):
        service = self.make_service()
        view = service.query("market", {"position": "GK"})
        self.assertEqual(view["role"], "market")
        self.assertGreater(view["total"], 0)
        self.assertTrue(all(t["position"] == "GK" for t in view["targets"]))
        self.assertGreaterEqual(view["budget"], 0)

    def test_market_classifies_three_transfer_types(self):
        service = self.make_service()
        view = service.query("market", {})
        kinds = {t["kind"] for t in view["targets"]}
        self.assertIn("free", kinds)
        self.assertIn("first-team", kinds)
        self.assertIn("academy", kinds)
        self.assertEqual(view["total"], sum(view["kinds"].values()))
        self.assertEqual(set(view["kinds"]), {"free", "first-team", "academy"})

    def test_market_filter_by_transfer_type(self):
        service = self.make_service()
        view = service.query("market", {"kind": "academy"})
        self.assertTrue(view["targets"])
        self.assertTrue(all(t["kind"] == "academy" for t in view["targets"]))
        self.assertTrue(all(t["age"] <= 21 for t in view["targets"]))
        free = service.query("market", {"kind": "free"})
        self.assertTrue(all(t["free"] and t["kind"] == "free" for t in free["targets"]))

    def test_propose_transfer_action_returns_result_and_market(self):
        service = self.make_service()
        state = service.state
        target = min(
            (p for p in state.players.values() if p.club_id != state.user_club_id),
            key=lambda p: p.valuation,
        )
        result = service.action("propose_transfer", {
            "player_id": target.id,
            "fee": int(target.valuation * 3),
            "weekly_wage": 50_000,
            "contract_years": 3,
        })
        self.assertEqual(result["role"], "transfer_result")
        self.assertIn("accepted", result)
        self.assertIn("market", result)

    def test_unaffordable_transfer_is_rejected_by_api(self):
        from manager.api.service import ServiceError

        service = self.make_service()
        state = service.state
        target = min(
            (p for p in state.players.values() if p.club_id != state.user_club_id),
            key=lambda p: p.valuation,
        )
        with self.assertRaises(ServiceError):
            service.action("propose_transfer", {
                "player_id": target.id,
                "fee": 999_999_999,
                "weekly_wage": 50_000,
                "contract_years": 3,
            })

    def test_renew_contract_action(self):
        service = self.make_service()
        state = service.state
        player = state.players[state.user_club().squad_ids[0]]
        result = service.action("renew_contract", {
            "player_id": player.id,
            "weekly_wage": player.contract.weekly_wage + 1000,
            "contract_years": 3,
        })
        self.assertTrue(result["renewed"])
        self.assertIn("message", result)

    def test_sell_player_action(self):
        service = self.make_service()
        state = service.state
        player = state.players[state.user_club().squad_ids[0]]
        result = service.action("sell_player", {
            "player_id": player.id,
            "fee": int(player.valuation * 0.9),
        })
        self.assertTrue(result["sold"])
        self.assertIn("market", result)

    def test_market_loan_tab_lists_loanable_players(self):
        service = self.make_service()
        view = service.query("market", {"kind": "loan"})
        self.assertTrue(view["targets"])
        self.assertTrue(all(t["loan"] for t in view["targets"]))
        self.assertTrue(all(not t["free"] for t in view["targets"]))
        self.assertEqual(view["loan_available"] >= len(view["targets"]), True)
        self.assertEqual(view["loans"]["incoming"], 0)

    def test_propose_loan_action_returns_market(self):
        from manager.systems.transfers import loan_eligible

        service = self.make_service()
        state = service.state
        target = next(
            p for p in state.players.values()
            if p.club_id is not None and loan_eligible(state, p)
        )
        parent = target.club_id
        result = service.action("propose_loan", {"player_id": target.id})
        self.assertEqual(result["role"], "transfer_result")
        self.assertIn("accepted", result)
        self.assertTrue(result["accepted"])
        self.assertIn("market", result)
        self.assertEqual(state.players[target.id].loaned_from, parent)

    def test_loan_out_action_returns_squad(self):
        service = self.make_service()
        state = service.state
        club = state.user_club()
        fringe = min(
            (p for pid in club.squad_ids if (p := state.players.get(pid)) is not None),
            key=lambda p: p.overall,
        )
        result = service.action("loan_out", {"player_id": fringe.id})
        self.assertEqual(result["role"], "squad")
        self.assertIn("message", result)
        self.assertTrue(result["message"])

    def test_market_exposes_window_and_offers(self):
        service = self.make_service()
        view = service.query("market", {})
        self.assertEqual(view["role"], "market")
        self.assertIn("window", view)
        self.assertTrue(view["window"]["open"])
        self.assertIsInstance(view["offers"], list)

    def test_accept_offer_action(self):
        from manager.systems.transfers import _generate_incoming_offers

        service = self.make_service()
        state = service.state
        _generate_incoming_offers(state)
        offer = next(o for o in state.incoming_offers if o.status == "pending")
        club = state.user_club()
        player = state.players[offer.player_id]
        buyer = state.clubs[offer.buyer_club_id]
        budget_before = club.finances.transfer_budget

        result = service.action("accept_offer", {"offer_id": offer.id})

        self.assertEqual(result["role"], "transfer_result")
        self.assertTrue(result["accepted"])
        self.assertEqual(state.players[player.id].club_id, buyer.id)
        self.assertEqual(club.finances.transfer_budget, budget_before + offer.fee)
        self.assertIn("market", result)

    def test_refuse_offer_action(self):
        from manager.systems.transfers import _generate_incoming_offers

        service = self.make_service()
        state = service.state
        _generate_incoming_offers(state)
        offer = next(o for o in state.incoming_offers if o.status == "pending")

        result = service.action("refuse_offer", {"offer_id": offer.id})

        self.assertEqual(result["role"], "transfer_result")
        self.assertTrue(result["refused"])
        self.assertEqual(next(o for o in state.incoming_offers if o.id == offer.id).status, "refused")

    def test_negotiate_offer_action(self):
        from manager.systems.transfers import _generate_incoming_offers

        service = self.make_service()
        state = service.state
        _generate_incoming_offers(state)
        offer = next(o for o in state.incoming_offers if o.status == "pending")
        club = state.user_club()
        player = state.players[offer.player_id]
        buyer = state.clubs[offer.buyer_club_id]
        budget_before = club.finances.transfer_budget
        counter = offer.fee // 2

        result = service.action("negotiate_offer", {"offer_id": offer.id, "fee": counter})

        self.assertEqual(result["role"], "transfer_result")
        self.assertTrue(result["accepted"])
        self.assertEqual(state.players[player.id].club_id, buyer.id)
        self.assertEqual(club.finances.transfer_budget, budget_before + counter)
        self.assertIn("market", result)


if __name__ == "__main__":
    unittest.main()