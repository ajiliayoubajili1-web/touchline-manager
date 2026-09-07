"""Transfers, contracts and transfer-budget spending.

Buying a player costs transfer budget plus wages; both are enforced against the
club's finances before anything is recorded. AI clubs accept or reject an offer
deterministically (same career seed, same decision). Free agents sign directly
with no fee. Contract renewals and selling players complete the picture.
"""

from __future__ import annotations

from manager.core.enums import NewsCategory, TransferStatus, TransferType
from manager.core.models import CareerState, Contract, IncomingOffer, NewsArticle, Player, Transfer
from manager.core.validate import (
    validate_transfer_affordability,
    validate_transfer_params,
)
from manager.rng import SeededRng


class TransferError(ValueError):
    pass


LOAN_MAX = 2


def transfer_window(state: CareerState) -> dict:
    """Which transfer window (if any) is currently open.

    Two windows per season:
      - Window 1 (summer): the opening weeks of a season.
      - Window 2 (winter): the weeks around the season's midpoint.

    Returns a dict with ``open`` (bool) and ``name`` (e.g. ``"summer"``,
    ``"winter"``, ``"closed"``), so the UI can communicate availability.
    """
    total_weeks = state.seasons[state.current_season].total_weeks
    week = state.current_week
    mid = total_weeks // 2

    summer_open = (0, 2)
    winter_open = (mid - 1, mid + 2)

    if summer_open[0] <= week <= summer_open[1]:
        return {"open": True, "name": "summer", "week": week, "weeks": list(summer_open)}
    if winter_open[0] <= week <= winter_open[1]:
        return {"open": True, "name": "winter", "week": week, "weeks": list(winter_open)}
    return {"open": False, "name": "closed", "week": week, "weeks": []}


def _generate_incoming_offers(state: CareerState) -> None:
    """Create deterministic AI bids for a selection of the user's players.

    Called lazily the first time the market is opened within a transfer window,
    so the same career seed always yields the same offers at that point in the
    season. Offers are only generated for the user's club.
    """
    try:
        window = transfer_window(state)
        if not window["open"]:
            return
    except KeyError:
        return

    key = f"{state.current_season}::{window['name']}"
    if getattr(state, "_offers_generated", None) == key:
        return

    club = state.user_club()
    rng = SeededRng(state.seed)
    candidates = []
    for player in state.players.values():
        if player.retired or player.club_id != club.id or player.loaned_from is not None:
            continue
        if player.contract is None:
            continue
        offer_chance = _offer_likelihood(state, player, rng)
        candidates.append((offer_chance, player))
    candidates.sort(key=lambda c: -c[0])
    candidates = candidates[:5]

    existing = {o.player_id for o in state.incoming_offers if o.status == "pending"}
    for chance, player in candidates:
        if player.id in existing:
            continue
        buyer = _pick_buyer(state, player, rng)
        if buyer is None:
            continue
        fee, wage, years = _offer_terms(state, player, buyer, rng)
        if fee <= 0:
            continue
        offer = IncomingOffer(
            id=f"ofr_{state.current_season}_{window['name']}_{len(state.incoming_offers) + 1:03d}",
            player_id=player.id,
            buyer_club_id=buyer.id,
            fee=fee,
            weekly_wage=wage,
            contract_years=years,
            season=state.current_season,
            week=state.current_week,
            status="pending",
        )
        state.incoming_offers.append(offer)
        _news(state, NewsCategory.TRANSFER_RUMOR,
              f"{buyer.name} make an offer for {player.full_name}",
              [club.id, buyer.id], [player.id])

    state._offers_generated = key


def _require_window(state: CareerState, action: str = "move") -> str:
    window = transfer_window(state)
    if not window["open"]:
        raise TransferError(
            f"The transfer window is closed — you can {action} players "
            f"during the summer or winter windows only."
        )
    return window["name"]


def accept_offer(state: CareerState, offer_id: str) -> dict:
    """Accept an AI club's bid for one of our players and complete the sale."""
    _generate_incoming_offers(state)
    window_name = _require_window(state, "sell")
    club = state.user_club()
    offer = next((o for o in state.incoming_offers if o.id == offer_id), None)
    if offer is None:
        raise TransferError("no such offer")
    if offer.status != "pending":
        raise TransferError("that offer is no longer on the table")
    if offer.buyer_club_id == club.id:
        raise TransferError("cannot accept an offer from your own club")

    player = _require_player(state, offer.player_id)
    if player.club_id != club.id:
        raise TransferError(f"{player.full_name} no longer plays for {club.name}")
    if player.loaned_from is not None:
        raise TransferError(f"{player.full_name} is on loan and cannot be sold")

    buyer = state.clubs[offer.buyer_club_id]
    transfer = _new_transfer(
        state, player, buyer.id,
        offer.fee, offer.weekly_wage, offer.contract_years,
    )
    _complete_transfer(state, transfer)
    offer.status = "accepted"
    _news(state, NewsCategory.TRANSFER_DONE,
          f"{player.full_name} joins {buyer.name} for {offer.fee:,}",
          [club.id, buyer.id], [player.id])
    return {
        "accepted": True,
        "player": player.full_name,
        "to": buyer.name,
        "fee": offer.fee,
        "window": window_name,
        "message": f"{player.full_name} joins {buyer.name} for {offer.fee:,}.",
    }


def refuse_offer(state: CareerState, offer_id: str) -> dict:
    """Decline an AI club's bid for one of our players."""
    club = state.user_club()
    offer = next((o for o in state.incoming_offers if o.id == offer_id), None)
    if offer is None:
        raise TransferError("no such offer")
    if offer.status != "pending":
        raise TransferError("that offer is no longer on the table")
    offer.status = "refused"
    player = state.players.get(offer.player_id)
    buyer = state.clubs[offer.buyer_club_id]
    return {
        "refused": True,
        "player": player.full_name if player else offer.player_id,
        "from": buyer.name,
        "message": f"{club.name} turn down {buyer.name}'s offer.",
    }


def negotiate_offer(state: CareerState, offer_id: str, fee: int) -> dict:
    """Counter an AI club's bid for one of our players with a new fee.

    The buying club weighs the counter against their original bid, the
    player's market value and their own budget. A reasonable counter is
    accepted on the spot; pushing too far lets them walk away.
    """
    _generate_incoming_offers(state)
    window_name = _require_window(state, "sell")
    club = state.user_club()
    offer = next((o for o in state.incoming_offers if o.id == offer_id), None)
    if offer is None:
        raise TransferError("no such offer")
    if offer.status != "pending":
        raise TransferError("that offer is no longer on the table")
    if offer.buyer_club_id == club.id:
        raise TransferError("cannot negotiate an offer from your own club")

    try:
        fee = int(fee)
    except (TypeError, ValueError):
        raise TransferError("transfer fee must be a number") from None
    if fee < 0:
        raise TransferError("transfer fee cannot be negative")

    player = _require_player(state, offer.player_id)
    if player.club_id != club.id:
        raise TransferError(f"{player.full_name} no longer plays for {club.name}")
    if player.loaned_from is not None:
        raise TransferError(f"{player.full_name} is on loan and cannot be sold")

    valuation = max(1, player.valuation)
    buyer = state.clubs[offer.buyer_club_id]
    if buyer.finances.transfer_budget < fee:
        offer.status = "withdrawn"
        return {
            "accepted": False,
            "player": player.full_name,
            "from": buyer.name,
            "fee": fee,
            "message": f"{buyer.name} cannot stretch to {fee:,} — talks are off.",
        }
    if fee > int(valuation * 2.5):
        offer.status = "withdrawn"
        _news(state, NewsCategory.TRANSFER_RUMOR,
              f"{buyer.name} walk away as {club.name}'s demands for {player.full_name} grow",
              [club.id, buyer.id], [player.id])
        return {
            "accepted": False,
            "player": player.full_name,
            "from": buyer.name,
            "fee": fee,
            "message": f"{buyer.name} balk at {fee:,} for {player.full_name} — the deal is off.",
        }

    if fee <= offer.fee:
        accepted = True
    else:
        stretch = 1.0 + max(0.0, (buyer.reputation - 50) / 80.0)
        ceiling = int(max(offer.fee * 1.25, valuation * 1.15) * stretch)
        accepted = fee <= ceiling

    if not accepted:
        offer.status = "withdrawn"
        _news(state, NewsCategory.TRANSFER_RUMOR,
              f"{buyer.name} walk away as talks with {club.name} stall",
              [club.id, buyer.id], [player.id])
        return {
            "accepted": False,
            "player": player.full_name,
            "from": buyer.name,
            "fee": fee,
            "message": f"{buyer.name} walk away after you pushed for {fee:,}.",
        }

    offer.fee = fee
    transfer = _new_transfer(
        state, player, buyer.id,
        fee, offer.weekly_wage, offer.contract_years,
    )
    _complete_transfer(state, transfer)
    offer.status = "accepted"
    _news(state, NewsCategory.TRANSFER_DONE,
          f"{buyer.name} meet {club.name}'s price for {player.full_name}",
          [club.id, buyer.id], [player.id])
    return {
        "accepted": True,
        "player": player.full_name,
        "to": buyer.name,
        "fee": fee,
        "window": window_name,
        "message": f"{buyer.name} meet your price — {player.full_name} joins for {fee:,}.",
    }


def _offer_likelihood(state: CareerState, player: Player, rng: SeededRng) -> float:
    """How interested AI clubs are in a given player (0..1)."""
    if _is_starter(state, player):
        return 0.06
    age = player.age_as_of(_season_year(state.current_season))
    rating = player.overall
    score = 0.0
    if rating >= 80:
        score += 0.35
    elif rating >= 74:
        score += 0.20
    elif rating >= 68:
        score += 0.12
    if age <= 24:
        score += 0.20
    elif age <= 29:
        score += 0.10
    jitter = 0.5 + rng.random(f"offer_like_{player.id}_{state.current_season}")
    return min(0.95, score * jitter)


def _pick_buyer(state: CareerState, player: Player, rng: SeededRng):
    """Choose an AI club that wants and can afford this player.

    Bidders are drawn from the world's top-reputation clubs, with the exact
    choice varied deterministically per player so different clubs pursue
    different targets rather than a single giant hoovering everyone up.
    """
    club = state.user_club()
    buyers = [
        c for c in state.clubs.values()
        if c.id != club.id
    ]
    buyers.sort(key=lambda c: (-c.reputation, c.id))
    pool = buyers[:10]
    offset = int(rng.random(f"offer_buyer_{player.id}_{state.current_season}") * len(pool))
    fee_guess = int(player.valuation * 0.95)
    for i in range(len(pool)):
        buyer = pool[(offset + i) % len(pool)]
        if buyer.finances.transfer_budget >= fee_guess:
            return buyer
    return None


def _offer_terms(state: CareerState, player: Player, buyer, rng: SeededRng):
    """Fee, wage and length an AI club offers for a player."""
    needle = max(1, player.valuation)
    factor = 0.8 + 0.25 * rng.random(f"offer_fee_{player.id}_{state.current_season}")
    fee = int(needle * factor)
    wage = max(player.contract.weekly_wage if player.contract else 0,
               int((max(player.overall, 46) - 45) ** 2.2 * 12))
    years = rng.randint(2, 4, f"offer_years_{player.id}_{state.current_season}")
    return fee, wage, years


def propose_loan(state: CareerState, player_id: str) -> dict:
    """Loan a fringe player from another club until the end of the season.

    The borrowing club pays the player's existing wage; no fee, no contract
    change. At season rollover the player returns to their parent club.
    """
    club = state.user_club()
    player = _require_player(state, player_id)

    _require_window(state, "loan")
    if player.retired:
        raise TransferError(f"{player.full_name} has retired")
    if player.club_id is None:
        raise TransferError(f"{player.full_name} is a free agent — sign them instead of loaning")
    if player.club_id == club.id:
        raise TransferError(f"{player.full_name} already plays for {club.name}")
    if player.loaned_from is not None:
        raise TransferError(f"{player.full_name} is already out on loan")

    loans_in = [
        p for p in state.players.values()
        if p.club_id == club.id and p.loaned_from is not None
    ]
    if len(loans_in) >= LOAN_MAX:
        raise TransferError(f"{club.name} already have {LOAN_MAX} players on loan — {player.full_name} cannot join yet")

    donor = state.club(player.club_id)
    if _is_starter(state, player):
        raise TransferError(f"{donor.name} count on {player.full_name} — they will not loan him out")

    if len(club.squad_ids) >= _squad_capacity() + LOAN_MAX:
        raise TransferError(
            f"the squad already carries its allowance of {LOAN_MAX} loans beyond the "
            f"{_squad_capacity()}-player cap — release or sell before loaning anyone in"
        )

    wage = player.contract.weekly_wage if player.contract else 0
    max_extra_game_wage = club.finances.weekly_wage_budget - club.finances.weekly_wage_spend
    if wage > max_extra_game_wage:
        raise TransferError(
            f"loaning {player.full_name} costs {wage:,}/wk but only {max_extra_game_wage:,}/wk of wage room remains"
        )

    _move_on_loan(state, player, donor.id, club.id)
    record = Transfer(
        id=f"trf_{state.current_season}_{len(state.transfers) + 1:03d}",
        player_id=player.id,
        from_club_id=donor.id,
        to_club_id=club.id,
        transfer_type=TransferType.LOAN,
        fee=0,
        weekly_wage=wage,
        contract_years=1,
        status=TransferStatus.COMPLETED,
        season=state.current_season,
        week=state.current_week,
        notes=f"loan return at the end of {state.current_season}",
    )
    state.transfers.append(record)
    _news(state, NewsCategory.TRANSFER_DONE,
          f"{player.full_name} joins {club.name} on loan from {donor.name}",
          [club.id, donor.id], [player.id])
    return {
        "accepted": True,
        "kind": "loan",
        "message": f"{player.full_name} joins {club.name} on loan from {donor.name} until the end of the season ({wage:,}/wk, no fee).",
    }


def loan_out_player(state: CareerState, player_id: str) -> dict:
    """Loan one of our own fringe players to the AI club with the roomiest need."""
    club = state.user_club()
    player = _require_player(state, player_id)

    _require_window(state, "loan")
    if player.club_id != club.id:
        raise TransferError(f"{player.full_name} does not play for {club.name}")
    if player.retired:
        raise TransferError(f"{player.full_name} has retired")
    if player.loaned_from is not None:
        raise TransferError(f"{player.full_name} is already out on loan")
    if _is_starter(state, player):
        raise TransferError(f"{player.full_name} is in the starting XI — drop them before loaning out")
    if len(club.squad_ids) <= 15:
        raise TransferError("the squad is too thin to loan anyone out")

    host = _best_loan_destination(state, player)
    if host is None:
        raise TransferError("no club has room for a loanee right now")

    _move_on_loan(state, player, club.id, host.id)
    record = Transfer(
        id=f"trf_{state.current_season}_{len(state.transfers) + 1:03d}",
        player_id=player.id,
        from_club_id=club.id,
        to_club_id=host.id,
        transfer_type=TransferType.LOAN,
        fee=0,
        weekly_wage=player.contract.weekly_wage if player.contract else 0,
        contract_years=1,
        status=TransferStatus.COMPLETED,
        season=state.current_season,
        week=state.current_week,
        notes="loan return at the end of the season",
    )
    state.transfers.append(record)
    _news(state, NewsCategory.TRANSFER_DONE,
          f"{player.full_name} joins {host.name} on loan from {club.name}",
          [club.id, host.id], [player.id])
    return {
        "accepted": True,
        "kind": "loan_out",
        "message": f"{player.full_name} joins {host.name} on loan until the end of the season.",
        "host": host.name,
        "host_id": host.id,
    }


def return_loans(state: CareerState) -> None:
    """End every active loan: players go home for the new season."""
    for player in list(state.players.values()):
        if player.retired or player.loaned_from is None:
            continue
        home_id = player.loaned_from
        host_id = player.club_id
        home = state.clubs.get(home_id)
        host = state.clubs.get(host_id) if host_id else None
        if host is not None:
            if player.id in host.squad_ids:
                host.squad_ids.remove(player.id)
            if player.contract:
                host.finances.weekly_wage_spend = max(0, host.finances.weekly_wage_spend - player.contract.weekly_wage)
            _strip_from_selection(state, host_id, player.id)
        player.club_id = home_id
        player.loaned_from = None
        if home is not None:
            if player.id not in home.squad_ids:
                home.squad_ids.append(player.id)
            if player.contract:
                home.finances.weekly_wage_spend += player.contract.weekly_wage


def loan_eligible(state: CareerState, player: Player) -> bool:
    """A player a club is willing to let go on loan: not a first-choice starter."""
    if player.retired or player.club_id is None or player.loaned_from is not None:
        return False
    if player.club_id == state.user_club_id:
        return False
    return not _is_starter(state, player)


def starter_map(state: CareerState) -> dict[str, set[str]]:
    """first-choice eleven per club, keyed by club id."""
    from manager.systems.squads import build_best_xi

    starters = {}
    for club in state.clubs.values():
        squad = [state.players[pid] for pid in club.squad_ids if pid in state.players]
        best = build_best_xi(club.id, squad, club.tactics.formation, available_only=True)
        starters[club.id] = set(best.starter_ids)
    return starters


def _squad_capacity() -> int:
    from manager.systems.season import SQUAD_SIZE

    return SQUAD_SIZE


def _season_year(season_id: str) -> int:
    return int(season_id.split("-")[0])


def _move_on_loan(state: CareerState, player: Player, donor_id: str, host_id: str) -> None:
    donor = state.club(donor_id)
    host = state.club(host_id)
    old_wage = player.contract.weekly_wage if player.contract else 0
    host.finances.weekly_wage_spend += old_wage
    donor.finances.weekly_wage_spend = max(0, donor.finances.weekly_wage_spend - old_wage)
    if player.id in donor.squad_ids:
        donor.squad_ids.remove(player.id)
    if player.id not in host.squad_ids:
        host.squad_ids.append(player.id)
    player.club_id = host_id
    player.loaned_from = donor_id
    player.morale = min(100, player.morale + 5)
    _strip_from_selection(state, donor_id, player.id)


def _strip_from_selection(state: CareerState, club_id: str, player_id: str) -> None:
    selection = state.selections.get(club_id)
    if selection is None:
        return
    if player_id in selection.starter_ids:
        selection.starter_ids.remove(player_id)
    if player_id in selection.substitute_ids:
        selection.substitute_ids.remove(player_id)
    if selection.captain_id == player_id:
        selection.captain_id = None
    if selection.set_piece_taker_id == player_id:
        selection.set_piece_taker_id = None


def _is_starter(state: CareerState, player: Player) -> bool:
    if player.club_id is None:
        return False
    from manager.systems.squads import build_best_xi

    club = state.club(player.club_id)
    squad = [state.players[pid] for pid in club.squad_ids if pid in state.players]
    best = build_best_xi(club.id, squad, club.tactics.formation, available_only=True)
    return player.id in best.starter_ids


def _best_loan_destination(state: CareerState, player: Player):
    """AI club most short-handed in this player's position that still has room."""
    from manager.systems.squads import build_best_xi

    cap = _squad_capacity() + LOAN_MAX
    position = player.preferred_position
    candidates = []
    for club in state.clubs.values():
        if club.id == player.club_id:
            continue
        if len(club.squad_ids) >= cap:
            continue
        squad = [state.players[pid] for pid in club.squad_ids if pid in state.players]
        best = build_best_xi(club.id, squad, club.tactics.formation, available_only=True)
        same_pos_rating = max(
            (state.players[pid].rating_at(position) for pid in best.starter_ids
             if pid in state.players and position in state.players[pid].positions),
            default=None,
        )
        candidates.append((club, -1 if same_pos_rating is None else same_pos_rating, club.id))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[1], c[2]))
    return candidates[0][0]


def propose_transfer(
    state: CareerState,
    player_id: str,
    fee: int,
    weekly_wage: int,
    contract_years: int,
) -> dict:
    """Offer a contract to a free agent or make a bid to an AI club."""
    club = state.user_club()
    player = _require_player(state, player_id)

    signing_free_agent = player.club_id is None
    if not signing_free_agent:
        _require_window(state, "sign")
    try:
        if signing_free_agent:
            validate_transfer_params(0, weekly_wage, contract_years)
        else:
            validate_transfer_params(fee, weekly_wage, contract_years)
        validate_transfer_affordability(club, 0 if signing_free_agent else fee, weekly_wage)
    except ValueError as exc:
        raise TransferError(str(exc)) from exc

    if player.club_id == club.id:
        raise TransferError(f"{player.full_name} already plays for {club.name}")

    if player.retired:
        raise TransferError(f"{player.full_name} has retired")

    if player.loaned_from is not None:
        raise TransferError(f"{player.full_name} is out on loan and cannot be signed this season")

    transfer = _new_transfer(state, player, club.id, 0 if player.club_id is None else fee, weekly_wage, contract_years)

    if signing_free_agent:
        _complete_transfer(state, transfer)
        return {
            "accepted": True,
            "kind": "free",
            "message": f"{player.full_name} signs for {club.name} ({weekly_wage}/wk, {contract_years} yrs).",
        }

    if _ai_accepts_transfer(state, player, fee, weekly_wage):
        _complete_transfer(state, transfer)
        return {
            "accepted": True,
            "kind": "bid",
            "message": f"{state.club(player.club_id).name} accept the bid for {player.full_name}.",
        }

    transfer.status = TransferStatus.DECLINED
    transfer.notes = "The selling club declined the offer."
    expected = transfer_valuation_fee(state, player)
    _news(state, NewsCategory.TRANSFER_RUMOR,
          f"{club.name} bid for {player.full_name} rejected",
          [club.id, transfer.from_club_id or ""], [player.id])
    return {
        "accepted": False,
        "kind": "bid",
        "message": f"{state.club(transfer.from_club_id).name} reject the offer for {player.full_name} "
                   f"(they would want around {expected:,}).",
    }


def renew_contract(
    state: CareerState,
    player_id: str,
    weekly_wage: int,
    contract_years: int,
) -> dict:
    """Extend one of our own player's contracts (new wage + length)."""
    club = state.user_club()
    player = _require_player(state, player_id)
    if player.club_id != club.id:
        raise TransferError(f"{player.full_name} does not play for {club.name}")
    if player.loaned_from is not None:
        raise TransferError(f"{player.full_name} is here on loan from "
                            f"{state.clubs[player.loaned_from].name} — his club holds the contract")

    try:
        validate_transfer_params(0, weekly_wage, contract_years)
    except ValueError as exc:
        raise TransferError(str(exc)) from exc

    old_wage = player.contract.weekly_wage if player.contract else 0
    delta = weekly_wage - old_wage
    if club.finances.weekly_wage_spend + delta > club.finances.weekly_wage_budget:
        raise TransferError(
            "weekly wage exceeds the remaining wage budget"
        )
    if delta > 0:
        club.finances.weekly_wage_spend += delta

    player.contract = Contract(
        player_id=player.id,
        club_id=club.id,
        weekly_wage=weekly_wage,
        start_season=state.current_season,
        end_season=_shift_season(state.current_season, contract_years),
    )
    _news(state, NewsCategory.CONTRACT,
          f"{player.full_name} agrees a new {contract_years}-year deal",
          [club.id], [player.id])
    return {"renewed": True, "player": player.full_name, "end_season": player.contract.end_season}


def sell_player(state: CareerState, player_id: str, fee: int) -> dict:
    """Sell one of our own players to free agency for a fee (simplified)."""
    club = state.user_club()
    player = _require_player(state, player_id)

    _require_window(state, "sell")
    if player.club_id != club.id:
        raise TransferError(f"{player.full_name} does not play for {club.name}")
    if player.loaned_from is not None:
        raise TransferError(f"{player.full_name} is on loan from "
                            f"{state.clubs[player.loaned_from].name} — loaneees are not for sale")
    if fee < 0:
        raise TransferError("transfer fee cannot be negative")

    if fee < int(player.valuation * 0.8):
        raise TransferError(
            f"No club will pay {fee:,} for {player.full_name} (valued at {player.valuation:,})."
        )

    old_wage = player.contract.weekly_wage if player.contract else 0
    club.finances.transfer_budget += fee
    club.finances.weekly_wage_spend = max(0, club.finances.weekly_wage_spend - old_wage)

    if player.id in club.squad_ids:
        club.squad_ids.remove(player.id)
    selection = state.selections.get(club.id)
    if selection is not None:
        selection.starter_ids = [pid for pid in selection.starter_ids if pid != player.id]
        selection.substitute_ids = [pid for pid in selection.substitute_ids if pid != player.id]
    player.club_id = None
    player.contract = None
    player.morale = max(0, player.morale + 8)

    _news(state, NewsCategory.TRANSFER_DONE,
          f"{club.name} sell {player.full_name}",
          [club.id], [player.id])
    return {"sold": True, "player": player.full_name, "fee": fee}


def _complete_transfer(state: CareerState, transfer: Transfer) -> None:
    player = state.players[transfer.player_id]
    buyer = state.club(transfer.to_club_id)

    for other in state.incoming_offers:
        if other.player_id == player.id and other.status == "pending":
            other.status = "withdrawn"

    if transfer.fee > 0:
        buyer.finances.transfer_budget = max(0, buyer.finances.transfer_budget - transfer.fee)

    old_wage = player.contract.weekly_wage if player.contract else 0
    buyer.finances.weekly_wage_spend += transfer.weekly_wage

    if transfer.from_club_id and transfer.from_club_id in state.clubs:
        seller = state.club(transfer.from_club_id)
        seller.finances.transfer_budget += transfer.fee
        seller.finances.weekly_wage_spend = max(0, seller.finances.weekly_wage_spend - old_wage)
        if player.id in seller.squad_ids:
            seller.squad_ids.remove(player.id)

    player.contract = Contract(
        player_id=player.id,
        club_id=buyer.id,
        weekly_wage=transfer.weekly_wage,
        start_season=state.current_season,
        end_season=_shift_season(state.current_season, transfer.contract_years),
    )
    player.club_id = buyer.id
    if player.id not in buyer.squad_ids:
        buyer.squad_ids.append(player.id)
    player.morale = min(100, player.morale + 12)

    transfer.status = TransferStatus.COMPLETED
    transfer.season = state.current_season
    transfer.week = state.current_week

    kind = "sign" if transfer.from_club_id is None else "transfer"
    _news(state, NewsCategory.TRANSFER_DONE,
          f"{buyer.name} complete the {kind} of {player.full_name}",
          [buyer.id, transfer.from_club_id] if transfer.from_club_id else [buyer.id],
          [player.id])


def _ai_accepts_transfer(state: CareerState, player: Player, fee: int, weekly_wage: int) -> bool:
    """Deterministic willingness of the selling (AI) club to part with a player.

    The fee must at least reach the club's asking premium above market value
    (starters and clubs with no cover demand more), and the wage offer must
    cover the player's current contract. Premiums tighten on harder
    difficulties and loosen by reputation clout and a deterministic slice of
    negotiation luck.
    """
    valuation = max(1, player.valuation)
    current_wage = player.contract.weekly_wage if player.contract else 0

    required = max(1, int(valuation * _asking_premium(state, player)))
    if fee < required:
        return False
    if weekly_wage < current_wage:
        return False
    return True


def _asking_premium(state: CareerState, player: Player, starters=None) -> float:
    """Multiplier of market value the selling club insists on for a player."""
    from manager.systems.balance import profile_for

    seller = state.club(player.club_id)
    buyer = state.user_club()

    if starters is not None:
        is_starter = player.id in starters.get(seller.id, set())
    else:
        is_starter = _is_starter(state, player)
    if is_starter:
        base = 1.35
    elif _has_backup(state, player):
        base = 1.10
    else:
        base = 1.24

    rating_gap = (buyer.reputation - seller.reputation) / 400.0
    rng = SeededRng(state.seed)
    jitter = 0.92 + 0.16 * rng.random(f"transfer_{player.id}")
    return max(0.75, base * (1.0 + rating_gap) * profile_for(state.difficulty).buying_premium * jitter)


def transfer_valuation_fee(state: CareerState, player: Player, starters=None) -> int:
    """Expected starting fee (rounded up to the nearest 50k) a club would take.

    Used as the market hint so the player can bid realistically on the first
    try instead of guessing at valuations.
    """
    if player.club_id is None:
        return 0
    valuation = max(1, player.valuation)
    fee = int(valuation * _asking_premium(state, player, starters))
    return ((fee + 49_999) // 50_000) * 50_000


def _has_backup(state: CareerState, player: Player) -> bool:
    if player.club_id is None:
        return False
    squad = [
        state.players[pid] for pid in state.club(player.club_id).squad_ids
        if pid in state.players and pid != player.id
    ]
    same = [
        p for p in squad
        if p.preferred_position == player.preferred_position
    ]
    return len(same) > 0


def _new_transfer(state, player, to_club_id, fee, weekly_wage, contract_years) -> Transfer:
    transfer = Transfer(
        id=f"trf_{state.current_season}_{len(state.transfers) + 1:03d}",
        player_id=player.id,
        from_club_id=player.club_id,
        to_club_id=to_club_id,
        transfer_type=TransferType.FREE if player.club_id is None else TransferType.PERMANENT,
        fee=fee,
        weekly_wage=weekly_wage,
        contract_years=contract_years,
        status=TransferStatus.PROPOSED,
        season=state.current_season,
        week=state.current_week,
    )
    state.transfers.append(transfer)
    return transfer


def _require_player(state: CareerState, player_id: str) -> Player:
    player = state.players.get(player_id)
    if player is None:
        raise TransferError(f"unknown player {player_id!r}")
    return player


def _shift_season(season_id: str, years: int) -> str:
    base = int(season_id.split("-")[0])
    return f"{base + years}-{str(base + years + 1)[2:]}"


def _news(state: CareerState, category: NewsCategory, headline: str, clubs, players) -> None:
    state.news.append(NewsArticle(
        id=f"news_{state.current_season}_w{state.current_week}_{len(state.news) + 1:03d}",
        season=state.current_season,
        week=state.current_week,
        category=category,
        headline=headline,
        body="",
        clubs_involved=[c for c in clubs if c],
        players_involved=players,
    ))
    state.news = state.news[-80:]