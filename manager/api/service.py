"""GameService: the validated command/query surface for the UI.

The service owns the current career session and rebuilds it from save files on
demand. Every command validates before mutating, and every query returns a
JSON-safe view model. The UI never touches models or storage directly.
"""

from __future__ import annotations

from dataclasses import asdict

from manager.api.careers import (
    CareerError,
    continue_career,
    new_career,
    save_new_career,
)
from manager.api.objectives import packages_for
from manager.core.enums import (
    AttackingApproach,
    DefensiveApproach,
    DefensiveLine,
    Difficulty,
    MatchEventType,
    Mentality,
    PassingStyle,
    PlayingStyle,
    Position,
    PressingIntensity,
    Tempo,
)
from manager.core.models import CareerState, Club, Player
from manager.core.validate import ValidationError, validate_squad_selection, validate_tactics
from manager.systems.squads import build_best_xi
from manager.save.files import delete_save, list_saves
from manager.data.coaches import coach_by_key, roster

def coach_name(key: str) -> str:
    profile = coach_by_key(key)
    return profile.name if profile else ""


class ServiceError(Exception):
    pass


class GameService:
    def __init__(self, save_dir=None):
        self.state: CareerState | None = None
        self.save_dir = save_dir

    # ---- session ---------------------------------------------------------

    def require_career(self) -> CareerState:
        if self.state is None:
            raise ServiceError("no career loaded")
        return self.state

    def create_career(self, payload: dict) -> dict:
        try:
            state = new_career(
                first_name=payload.get("first_name", ""),
                last_name=payload.get("last_name", ""),
                nationality=payload.get("nationality", "Valland"),
                club_id=payload.get("club_id", ""),
                difficulty=payload.get("difficulty", "manager"),
                objective_key=payload.get("objective", "steady"),
                seed=int(payload.get("seed", 42)),
                favourite_coach=payload.get("favourite_coach", ""),
            )
        except CareerError as exc:
            raise ServiceError(str(exc)) from exc
        save_new_career(state, self.save_dir)
        self.state = state
        return self.view_model("dashboard")

    def load_career(self, payload: dict) -> dict:
        try:
            career_id = payload.get("career_id", "")
            state = continue_career(career_id, self.save_dir)
        except CareerError as exc:
            raise ServiceError(str(exc)) from exc
        self.state = state
        return self.view_model("dashboard")

    def new_game(self) -> dict:
        self.state = None
        return {"role": "new_game"}

    def discard(self) -> dict:
        career = self.require_career()
        try:
            delete_save(career.career_id, self.save_dir)
        except OSError:
            pass
        self.state = None
        return {"role": "new_game"}

    def delete(self, payload: dict) -> dict:
        return self.discard()

    def reset_session(self, payload: dict) -> dict:
        self.state = None
        return {"role": "new_game"}

    # ---- actions ---------------------------------------------------------

    def action(self, command: str, payload: dict) -> dict:
        handler = getattr(self, f"_act_{command}", None)
        if handler is None:
            raise ServiceError(f"unknown action {command!r}")
        return handler(payload)

    def _act_save(self, payload: dict) -> dict:
        state = self.require_career()
        save_new_career(state, self.save_dir)
        return {"saved": True, "career_id": state.career_id}

    def _act_autoselect(self, payload: dict) -> dict:
        state = self.require_career()
        club = state.user_club()
        selection = build_best_xi(club.id, list(state.players.values()))
        state.selections[club.id] = selection
        return self.view_model("squad")

    def _act_set_selection(self, payload: dict) -> dict:
        state = self.require_career()
        club = state.user_club()
        try:
            import copy

            selection = state.selections.get(club.id)
            if selection is None:
                from manager.core.models import SquadSelection

                selection = SquadSelection(club_id=club.id)
            candidate = copy.copy(selection)
            if "formation" in payload:
                validate_tactics(_tactics_with_formation(club, payload["formation"]))
                candidate.formation = payload["formation"]
            if "starter_ids" in payload:
                candidate.starter_ids = payload["starter_ids"]
            if "substitute_ids" in payload:
                candidate.substitute_ids = payload["substitute_ids"]
            if "captain_id" in payload:
                if payload["captain_id"] and payload["captain_id"] not in candidate.starter_ids:
                    raise ValidationError("the captain must be in the starting XI")
                candidate.captain_id = payload["captain_id"]
            validate_squad_selection(candidate, state.players)
            state.selections[club.id] = candidate
        except ValidationError as exc:
            raise ServiceError(f"invalid selection: {exc}") from exc
        return self.view_model("squad")

    def _act_set_tactics(self, payload: dict) -> dict:
        state = self.require_career()
        club = state.user_club()
        from dataclasses import replace

        field_types = _tactics_field_types()
        updates = {}
        for key, value in payload.items():
            if key not in field_types:
                raise ServiceError(f"unknown tactics field {key!r}")
            updates[key] = _coerce_tactics_value(key, value, field_types[key])
        candidate = replace(club.tactics, **updates)
        try:
            validate_tactics(candidate)
        except ValidationError as exc:
            raise ServiceError(f"invalid tactics: {exc}") from exc
        club.tactics = candidate
        return self.view_model("tactics")

    def _act_play_week(self, payload: dict) -> dict:
        state = self.require_career()
        from manager.systems.match import simulate_week

        outcome = simulate_week(state)
        if outcome.get("finished"):
            state.seasons[state.current_season].finished = True
        return matchday_view(state, outcome)

    def _act_play_to(self, payload: dict) -> dict:
        state = self.require_career()
        from manager.systems.match import simulate_to_week

        try:
            target = int(payload.get("week", 0))
            outcome = simulate_to_week(state, target)
        except ValueError as exc:
            raise ServiceError(str(exc)) from exc
        state.seasons[state.current_season].finished = (
            outcome.get("finished") or state.current_week >= state.seasons[state.current_season].total_weeks
        )
        return matchday_view(state, outcome)

    def _act_play_season(self, payload: dict) -> dict:
        state = self.require_career()
        from manager.systems.match import simulate_season

        outcome = simulate_season(state)
        state.seasons[state.current_season].finished = True
        return matchday_view(state, outcome)

    def _act_start_next_season(self, payload: dict) -> dict:
        state = self.require_career()
        from manager.systems.season import SeasonError, start_next_season

        try:
            start_next_season(state)
        except SeasonError as exc:
            raise ServiceError(str(exc)) from exc
        save_new_career(state, self.save_dir)
        return self.view_model("dashboard")

    def _act_propose_transfer(self, payload: dict) -> dict:
        state = self.require_career()
        from manager.systems.transfers import TransferError, propose_transfer

        try:
            result = propose_transfer(
                state,
                player_id=payload.get("player_id", ""),
                fee=int(payload.get("fee", 0)),
                weekly_wage=int(payload.get("weekly_wage", 0)),
                contract_years=int(payload.get("contract_years", 2)),
            )
        except (TransferError, ValueError) as exc:
            raise ServiceError(str(exc)) from exc
        save_new_career(state, self.save_dir)
        result["role"] = "transfer_result"
        result["market"] = market_view(state)
        return result

    def _act_accept_offer(self, payload: dict) -> dict:
        state = self.require_career()
        from manager.systems.transfers import TransferError, accept_offer

        try:
            result = accept_offer(state, payload.get("offer_id", ""))
        except TransferError as exc:
            raise ServiceError(str(exc)) from exc
        save_new_career(state, self.save_dir)
        result["role"] = "transfer_result"
        result["market"] = market_view(state)
        return result

    def _act_refuse_offer(self, payload: dict) -> dict:
        state = self.require_career()
        from manager.systems.transfers import TransferError, refuse_offer

        try:
            result = refuse_offer(state, payload.get("offer_id", ""))
        except TransferError as exc:
            raise ServiceError(str(exc)) from exc
        save_new_career(state, self.save_dir)
        result["role"] = "transfer_result"
        result["market"] = market_view(state)
        return result

    def _act_negotiate_offer(self, payload: dict) -> dict:
        state = self.require_career()
        from manager.systems.transfers import TransferError, negotiate_offer

        try:
            result = negotiate_offer(
                state,
                offer_id=payload.get("offer_id", ""),
                fee=int(payload.get("fee", 0)),
            )
        except (TransferError, ValueError) as exc:
            raise ServiceError(str(exc)) from exc
        save_new_career(state, self.save_dir)
        result["role"] = "transfer_result"
        result["market"] = market_view(state)
        return result

    def _act_renew_contract(self, payload: dict) -> dict:
        state = self.require_career()
        from manager.systems.transfers import TransferError, renew_contract

        try:
            result = renew_contract(
                state,
                player_id=payload.get("player_id", ""),
                weekly_wage=int(payload.get("weekly_wage", 0)),
                contract_years=int(payload.get("contract_years", 2)),
            )
        except (TransferError, ValueError) as exc:
            raise ServiceError(str(exc)) from exc
        save_new_career(state, self.save_dir)
        result["role"] = "transfer_result"
        result["message"] = f"{result['player']} signs until {result['end_season']}."
        result["renewals"] = renewal_view(state)
        return result

    def _act_sell_player(self, payload: dict) -> dict:
        state = self.require_career()
        from manager.systems.transfers import TransferError, sell_player

        try:
            result = sell_player(
                state,
                player_id=payload.get("player_id", ""),
                fee=int(payload.get("fee", 0)),
            )
        except (TransferError, ValueError) as exc:
            raise ServiceError(str(exc)) from exc
        save_new_career(state, self.save_dir)
        result["role"] = "transfer_result"
        result["message"] = f"{result['player']} sold for {result['fee']:,}."
        result["market"] = market_view(state)
        return result

    def _act_loan_out(self, payload: dict) -> dict:
        state = self.require_career()
        from manager.systems.transfers import TransferError, loan_out_player

        try:
            result = loan_out_player(state, player_id=payload.get("player_id", ""))
        except (TransferError, ValueError) as exc:
            raise ServiceError(str(exc)) from exc
        save_new_career(state, self.save_dir)
        view = self.view_model("squad")
        view["message"] = result["message"]
        return view

    def _act_propose_loan(self, payload: dict) -> dict:
        state = self.require_career()
        from manager.systems.transfers import TransferError, propose_loan

        try:
            result = propose_loan(state, player_id=payload.get("player_id", ""))
        except (TransferError, ValueError) as exc:
            raise ServiceError(str(exc)) from exc
        save_new_career(state, self.save_dir)
        result["role"] = "transfer_result"
        result["market"] = market_view(state)
        return result

    def _act_set_player_plan(self, payload: dict) -> dict:
        state = self.require_career()
        from manager.systems.development import apply_training_plan
        from manager.core.validate import ValidationError

        try:
            apply_training_plan(
                state,
                player_id=payload.get("player_id", ""),
                focus=payload.get("focus", ""),
                intensity=payload.get("intensity", ""),
                role=payload.get("role", ""),
                duty=payload.get("duty", ""),
            )
        except ValidationError as exc:
            raise ServiceError(str(exc)) from exc
        return training_view(state)

    # ---- queries ---------------------------------------------------------

    def query(self, name: str, params: dict) -> dict:
        handler = getattr(self, f"_q_{name}", None)
        if handler is None:
            raise ServiceError(f"unknown query {name!r}")
        return handler(params)

    def _q_setup(self, params: dict) -> dict:
        seed = int(params.get("seed", 42))
        return build_setup_view(seed)

    def _q_dashboard(self, params: dict) -> dict:
        return self.view_model("dashboard")

    def _q_squad(self, params: dict) -> dict:
        return self.view_model("squad")

    def _q_tactics(self, params: dict) -> dict:
        return self.view_model("tactics")

    def _q_player(self, params: dict) -> dict:
        state = self.require_career()
        player_id = params.get("player_id", "")
        player = state.players.get(player_id)
        if player is None:
            raise ServiceError(f"unknown player {player_id!r}")
        return player_view(state, player)

    def _q_careers(self, params: dict) -> dict:
        return {"careers": list_saves(self.save_dir)}

    def _q_fixtures(self, params: dict) -> dict:
        return fixtures_view(self.require_career())

    def _q_results(self, params: dict) -> dict:
        return results_view(self.require_career())

    def _q_standings(self, params: dict) -> dict:
        return standings_view(self.require_career())

    def _q_market(self, params: dict) -> dict:
        return market_view(
            self.require_career(),
            q=params.get("q", ""),
            position=params.get("position", ""),
            kind=params.get("kind", ""),
        )

    def _q_training(self, params: dict) -> dict:
        return training_view(self.require_career())

    def _q_news(self, params: dict) -> dict:
        return news_view(
            self.require_career(),
            category=params.get("category", ""),
            limit=int(params.get("limit", 40)),
        )

    def _q_cup(self, params: dict) -> dict:
        return cup_view(self.require_career())

    def _q_clubs(self, params: dict) -> dict:
        return clubs_view()

    def _q_session(self, params: dict) -> dict:
        if self.state is None:
            return {"in_career": False}
        state = self.state
        club = state.user_club()
        return {
            "in_career": True,
            "career_id": state.career_id,
            "title": state.title,
            "club": club.name,
            "difficulty": str(state.difficulty),
            "season": state.current_season,
            "week": state.current_week,
        }

    # ---- view models -----------------------------------------------------

    def view_model(self, name: str) -> dict:
        state = self.require_career()
        if name == "dashboard":
            return dashboard_view(state)
        if name == "squad":
            return squad_view(state)
        if name == "tactics":
            return tactics_view(state)
        raise ServiceError(f"no view model {name!r}")


def _tactics_with_formation(club: Club, formation: str):
    from dataclasses import replace

    return replace(club.tactics, formation=formation)


_TACTICS_FIELD_TYPES = None


def _tactics_field_types() -> dict:
    global _TACTICS_FIELD_TYPES
    if _TACTICS_FIELD_TYPES is None:
        import typing

        from manager.core.models import Tactics

        _TACTICS_FIELD_TYPES = typing.get_type_hints(Tactics)
    return _TACTICS_FIELD_TYPES


def _coerce_tactics_value(key: str, value, expected):
    """Convert a raw UI value to the field's declared type, rejecting junk."""
    from enum import Enum

    if isinstance(expected, type) and issubclass(expected, Enum):
        try:
            return expected(value)
        except ValueError as exc:
            raise ServiceError(
                f"invalid value {value!r} for tactics field {key!r}"
            ) from exc
    if not isinstance(value, expected):
        raise ServiceError(
            f"invalid value {value!r} for tactics field {key!r}: expected {expected.__name__}"
        )
    return value


# ---------------------------------------------------------------------------
# View models
# ---------------------------------------------------------------------------

def _final_position(state: CareerState) -> int | None:
    if not _season_finished(state):
        return None
    from manager.systems.fixtures import compute_standings
    for index, row in enumerate(compute_standings(state.fixtures)):
        if row.club_id == state.user_club_id:
            return index + 1
    return None


def _season_finished(state: CareerState) -> bool:
    season = state.seasons.get(state.current_season)
    return bool(season and season.finished)


def dashboard_view(state: CareerState) -> dict:
    club = state.user_club()
    return {
        "role": "dashboard",
        "title": state.title,
        "manager": {
            "name": state.manager.full_name,
            "nationality": state.manager.nationality,
            "reputation": state.manager.reputation,
            "favourite_coach": state.manager.favourite_coach,
            "favourite_coach_name": coach_name(state.manager.favourite_coach),
        },
        "club": {
            "id": club.id,
            "name": club.name,
            "city": club.city,
            "stadium": club.stadium_name,
            "capacity": club.capacity,
            "primary": club.primary_color,
            "secondary": club.secondary_color,
            "reputation": club.reputation,
        },
        "season": {
            "id": state.current_season,
            "week": state.current_week,
            "difficulty": str(state.difficulty),
            "finished": _season_finished(state),
            "final_position": _final_position(state),
        },
        "finances": {
            "balance": club.finances.balance,
            "transfer_budget": club.finances.transfer_budget,
            "weekly_wage_budget": club.finances.weekly_wage_budget,
            "weekly_wage_spend": club.finances.weekly_wage_spend,
        },
        "board": asdict(club.board),
        "objectives": [
            {
                "label": objective.label,
                "achieved": objective.achieved,
                "season": objective.season,
                "reward": objective.reward,
            }
            for objective in club.objectives
        ],
        "next_match": next_match_view(state),
        "news": [n.headline for n in state.news[-5:]],
    }


def squad_view(state: CareerState) -> dict:
    club = state.user_club()
    selection = state.selections.get(club.id)
    starters = set(selection.starter_ids) if selection else set()
    bench = set(selection.substitute_ids) if selection else set()

    players = [state.players[pid] for pid in club.squad_ids if pid in state.players]
    rows = []
    for player in players:
        rows.append(_player_row(state, player, starters, bench))

    rows.sort(key=lambda r: (-r["overall"], r["last_name"]))
    for row in rows:
        row["loanable"] = (
            row["loan_from"] is None
            and not row["in_xi"]
            and len(rows) > 15
        )
    return {
        "role": "squad",
        "club": {"id": club.id, "name": club.name, "primary": club.primary_color, "secondary": club.secondary_color},
        "formation": selection.formation if selection else "4-3-3",
        "starter_ids": selection.starter_ids if selection else [],
        "substitute_ids": selection.substitute_ids if selection else [],
        "captain_id": selection.captain_id if selection else None,
        "players": rows,
        "counts": {
            "total": len(rows),
            "injured": sum(1 for r in rows if r["injury"]),
            "suspended": sum(1 for r in rows if r["suspension"]),
        },
    }


def training_view(state: CareerState) -> dict:
    club = state.user_club()
    from manager.systems.development import DUTIES, FOCUSES, INTENSITIES, allowed_roles

    rows = []
    for pid in club.squad_ids:
        player = state.players.get(pid)
        if player is None:
            continue
        rows.append({
            "id": player.id,
            "name": player.full_name,
            "position": str(player.preferred_position),
            "overall": player.overall,
            "potential": player.potential,
            "age": player.age_as_of(_season_year(state.current_season)),
            "energy": player.energy,
            "morale": player.morale,
            "focus": str(player.training_focus),
            "intensity": str(player.training_intensity),
            "role": str(player.tactical_role),
            "duty": str(player.tactical_duty),
            "allowed_roles": allowed_roles(player),
            "last_dev": player.development_history[-1].note
            if player.development_history else None,
        })
    rows.sort(key=lambda r: (-r["overall"], r["name"]))
    return {
        "role": "training",
        "club": {"name": club.name, "id": club.id},
        "focuses": FOCUSES,
        "intensities": INTENSITIES,
        "duties": DUTIES,
        "players": rows,
    }


def tactics_view(state: CareerState) -> dict:
    club = state.user_club()
    enum_options = {
        "mentality": [i.value for i in Mentality],
        "playing_style": [i.value for i in PlayingStyle],
        "pressing": [i.value for i in PressingIntensity],
        "passing": [i.value for i in PassingStyle],
        "tempo": [i.value for i in Tempo],
        "defensive_line": [i.value for i in DefensiveLine],
        "defensive_approach": [i.value for i in DefensiveApproach],
        "attacking_approach": [i.value for i in AttackingApproach],
    }
    return {
        "role": "tactics",
        "club": {"name": club.name},
        "tactics": asdict(club.tactics),
        "game_plan": _game_plan(state),
        "options": {
            "formations": ["4-3-3", "4-4-2", "4-2-3-1", "3-5-2", "5-3-2", "4-3-2-1", "3-4-3", "4-1-4-1"],
            **enum_options,
        },
    }


_FAMILY = {
    "GK": {"GK"},
    "DF": {"LB", "CB", "RB", "WB"},
    "MF": {"DM", "CM", "AM", "LM", "RM"},
    "FW": {"LW", "RW", "CF", "ST"},
}


def _game_plan(state: CareerState) -> dict:
    """The starting XI laid out line-by-line (GK / defences / mids / attack)."""
    club = state.user_club()
    selection = state.selections.get(club.id)
    if selection is None or not selection.starter_ids:
        from manager.systems.squads import build_best_xi

        squad = [state.players[pid] for pid in club.squad_ids if pid in state.players]
        selection = build_best_xi(club.id, squad, club.tactics.formation, available_only=True)

    from manager.core.validate import parse_formation

    defenders, midfielders, forwards = parse_formation(selection.formation)
    slots = {"DF": defenders, "MF": midfielders, "FW": forwards}
    starters = [state.players[pid] for pid in selection.starter_ids if pid in state.players]

    def card(player) -> dict:
        return {
            "id": player.id,
            "name": player.full_name,
            "overall": player.overall,
            "position": str(player.preferred_position),
            "fitness": player.fitness,
            "energy": player.energy,
            "injury": player.injury.injury_type if player.injury and player.injury.weeks_remaining > 0 else None,
            "captain": player.id == selection.captain_id,
        }

    goalkeeper = next((p for p in starters if p.preferred_position == Position.GK
                       or Position.GK in p.positions), None)
    outfield = [p for p in starters if p is not goalkeeper]

    rows: list[dict] = [{"line": "GK", "players": [card(goalkeeper)] if goalkeeper else []}]
    placed_ids = {goalkeeper.id} if goalkeeper else set()
    for line in ("DF", "MF", "FW"):
        pool = sorted(
            (p for p in outfield if str(p.preferred_position) in _FAMILY[line]),
            key=lambda p: -p.overall,
        )
        chosen = pool[: slots[line]]
        rows.append({"line": line, "players": [card(p) for p in chosen]})
        placed_ids.update(p.id for p in chosen)

    remaining = sorted((p for p in outfield if p.id not in placed_ids),
                       key=lambda p: -p.overall)
    for row in rows:
        if row["line"] == "GK":
            continue
        while len(row["players"]) < slots[row["line"]] and remaining:
            row["players"].append(card(remaining.pop(0)))
    while remaining:
        rows[-1]["players"].append(card(remaining.pop(0)))

    substitutes = [
        card(state.players[pid]) for pid in selection.substitute_ids if pid in state.players
    ]
    return {
        "formation": selection.formation,
        "rows": rows,
        "substitutes": substitutes,
    }


def player_view(state: CareerState, player: Player) -> dict:
    club = state.user_club()
    row = _player_row(state, player, set(), set())
    row["role"] = "player"
    row["attributes"] = asdict(player.attributes)
    row["personality"] = [str(t) for t in player.personality]
    row["two_footedness"] = player.two_footedness
    row["flair"] = player.flair
    row["career"] = {
        "appearances": player.career_appearances,
        "goals": player.career_goals,
        "assists": player.career_assists,
    }
    row["season_stats"] = [
        asdict(stats) for stats in player.season_stats[-1:]
    ]
    row["development"] = [asdict(r) for r in player.development_history[-3:]]
    return row


def build_setup_view(seed: int) -> dict:
    """View model for the career-setup screen (club picker)."""
    from manager.core.models import Player
    from manager.data.world import cached_world
    from manager.systems.balance import PROFILES

    world = cached_world(seed)
    clubs_view = []
    for club in sorted(world.clubs, key=lambda c: -c.reputation):
        squad = [p for p in world.players if p.club_id == club.id and isinstance(p, Player)]
        strengths = sorted(p.overall for p in squad)
        best5 = strengths[-5:] if len(strengths) >= 5 else strengths
        clubs_view.append({
            "id": club.id,
            "name": club.name,
            "city": club.city,
            "stadium": club.stadium_name,
            "capacity": club.capacity,
            "primary": club.primary_color,
            "secondary": club.secondary_color,
            "reputation": club.reputation,
            "transfer_budget": club.finances.transfer_budget,
            "avg_best5": round(sum(best5) / max(1, len(best5)), 1),
        })

    return {
        "role": "setup",
        "seed": seed,
        "clubs": clubs_view,
        "difficulties": [str(d.value) for d in Difficulty],
        "nationalities": ["Valland", "Northeim", "Serevia", "Caldria", "Ostara",
                          "Meridian", "Vantica", "Ashkefar", "Bralore", "Thuvia", "Kyren"],
        "coaches": roster(),
        "objectives": [
            {
                "key": package.key,
                "label": package.label,
                "description": package.description,
            }
            for package in packages_for(Difficulty.MANAGER)
        ],
    }


def _player_row(state: CareerState, player: Player, starters: set, bench: set) -> dict:
    contract = player.contract
    return {
        "id": player.id,
        "first_name": player.first_name,
        "last_name": player.last_name,
        "full_name": player.full_name,
        "nationality": player.nationality,
        "age": player.age_as_of(_season_year(state.current_season)),
        "positions": [str(p) for p in player.positions],
        "preferred_position": str(player.preferred_position),
        "overall": player.overall,
        "potential": player.potential,
        "form": player.form,
        "morale": player.morale,
        "fitness": player.fitness,
        "valuation": player.valuation,
        "wage": contract.weekly_wage if contract else None,
        "contract_end": contract.end_season if contract else "Free agent",
        "squad_number": contract.squad_number if contract else None,
        "injury": {
            "type": player.injury.injury_type,
            "weeks": player.injury.weeks_remaining,
        } if player.injury else None,
        "suspension": player.suspension.matches_remaining if player.suspension else None,
        "training_focus": str(player.training_focus),
        "training_intensity": str(player.training_intensity),
        "tactical_role": str(player.tactical_role),
        "tactical_duty": str(player.tactical_duty),
        "in_xi": player.id in starters,
        "on_bench": player.id in bench,
        "loan_from": (state.clubs[player.loaned_from].name
                      if player.loaned_from and player.loaned_from in state.clubs else None),
    }


def _season_year(season_id: str) -> int:
    try:
        return int(season_id.split("-")[0])
    except ValueError:
        return 2026


# ---------------------------------------------------------------------------
# Phase 3: fixtures, results, standings, matchday
# ---------------------------------------------------------------------------

def _next_match(state: CareerState):
    upcoming = sorted(
        (f for f in state.fixtures
         if f.season == state.current_season
         and f.status.value == "scheduled"
         and (f.home_club_id == state.user_club_id or f.away_club_id == state.user_club_id)),
        key=lambda f: (f.week, f.id),
    )
    if not upcoming:
        return None
    return upcoming[0]


def next_match_view(state: CareerState) -> dict | None:
    fixture = _next_match(state)
    if fixture is None:
        return None
    home = state.club(fixture.home_club_id)
    away = state.club(fixture.away_club_id)
    comp = state.competitions.get(fixture.competition_id)
    is_home = fixture.home_club_id == state.user_club_id
    return {
        "week": fixture.week,
        "competition": comp.name if comp else fixture.competition_id,
        "venue": "Home" if is_home else "Away",
        "opponent": away.name if is_home else home.name,
        "opponent_rep": away.reputation if is_home else home.reputation,
        "stadium": home.stadium_name,
        "date": fixture.date,
        "date_label": _date_label(fixture.date) if fixture.date else f"Week {fixture.week}",
        "fixture_id": fixture.id,
    }


def _date_label(iso_date: str) -> str:
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso_date).strftime("%a %d %b")
    except ValueError:
        return ""


def _user_result(state: CareerState, fixture) -> str:
    if not fixture.score or fixture.status.value != "played":
        return ""
    me = state.user_club_id
    home_win = fixture.score[0] > fixture.score[1]
    away_win = fixture.score[1] > fixture.score[0]
    if fixture.home_club_id == me:
        return "W" if home_win else "L" if away_win else "D"
    return "W" if away_win else "L" if home_win else "D"


def fixtures_view(state: CareerState) -> dict:
    from datetime import datetime

    rows = []
    for fixture in sorted(
        (f for f in state.fixtures if f.season == state.current_season
         and (f.home_club_id == state.user_club_id or f.away_club_id == state.user_club_id)),
        key=lambda f: (f.week, 0 if f.competition_id == "apex_division" else 1, f.id),
    ):
        home = state.club(fixture.home_club_id)
        away = state.club(fixture.away_club_id)
        comp = state.competitions.get(fixture.competition_id)
        is_home = fixture.home_club_id == state.user_club_id
        date_label = ""
        month = ""
        weekday = ""
        if fixture.date:
            try:
                day = datetime.fromisoformat(fixture.date)
                date_label = day.strftime("%a %d %b")
                weekday = day.strftime("%A")
                month = day.strftime("%B")
            except ValueError:
                pass
        rows.append({
            "week": fixture.week,
            "date": fixture.date,
            "date_label": date_label,
            "weekday": weekday,
            "month": month,
            "home": home.name,
            "away": away.name,
            "venue": "Home" if is_home else "Away",
            "opponent": away.name if is_home else home.name,
            "competition": comp.name if comp else fixture.competition_id,
            "competition_id": fixture.competition_id,
            "cup": fixture.round != "",
            "round": fixture.round,
            "played": fixture.status.value == "played",
            "score": f"{fixture.home_goals}-{fixture.away_goals}" if fixture.score else None,
            "is_user": True,
            "result": _user_result(state, fixture),
        })
    return {
        "role": "fixtures",
        "club": {"name": state.user_club().name},
        "week": state.current_week,
        "finished": state.seasons[state.current_season].finished,
        "fixtures": rows,
    }


def results_view(state: CareerState) -> dict:
    rows = []
    for fixture in sorted(
        (f for f in state.fixtures if f.season == state.current_season
         and f.status.value == "played"
         and (f.home_club_id == state.user_club_id or f.away_club_id == state.user_club_id)),
        key=lambda f: (f.week, f.id),
        reverse=True,
    ):
        home = state.club(fixture.home_club_id)
        away = state.club(fixture.away_club_id)
        my = fixture.home_goals if fixture.home_club_id == state.user_club_id else fixture.away_goals
        other = fixture.away_goals if fixture.home_club_id == state.user_club_id else fixture.home_goals
        rows.append({
            "week": fixture.week,
            "home": home.name,
            "away": away.name,
            "score": f"{my}-{other}",
            "result": "W" if my > other else "D" if my == other else "L",
            "attendance": fixture.attendance,
            "is_user": True,
        })
    return {"role": "results", "results": rows}


def standings_view(state: CareerState) -> dict:
    from manager.systems.fixtures import LEAGUE_ID, compute_standings

    table = compute_standings(state.fixtures)
    position_map = {row.club_id: index + 1 for index, row in enumerate(table)}
    rows = []
    for index, row in enumerate(table):
        club = state.clubs.get(row.club_id)
        rows.append({
            "position": index + 1,
            "club": club.name if club else row.club_id,
            "played": row.played,
            "won": row.won,
            "drawn": row.drawn,
            "lost": row.lost,
            "goals_for": row.goals_for,
            "goals_against": row.goals_against,
            "goal_difference": row.goal_difference,
            "points": row.points,
            "is_user": row.club_id == state.user_club_id,
        })
    return {
        "role": "standings",
        "competition": state.competitions[LEAGUE_ID].name if LEAGUE_ID in state.competitions else "Super League",
        "season": state.current_season,
        "week": state.current_week,
        "user_position": position_map.get(state.user_club_id),
        "rows": rows,
    }


def matchday_view(state: CareerState, outcome: dict) -> dict:
    week = outcome["week"]
    results = []
    for fixture in sorted(
        (f for f in state.fixtures if f.season == state.current_season and f.week == week),
        key=lambda f: f.id,
    ):
        home = state.club(fixture.home_club_id)
        away = state.club(fixture.away_club_id)
        my = fixture.home_club_id == state.user_club_id or fixture.away_club_id == state.user_club_id
        results.append({
            "home": home.name,
            "away": away.name,
            "score": f"{fixture.home_goals} - {fixture.away_goals}" if fixture.score else "-",
            "is_user": my,
            "attendance": fixture.attendance,
        })

    user_fixture = next(
        (f for f in state.fixtures if f.season == state.current_season and f.week == week
         and (f.home_club_id == state.user_club_id or f.away_club_id == state.user_club_id)),
        None,
    )
    top_performers = []
    if user_fixture is not None and user_fixture.ratings:
        own_set = set(
            user_fixture.team_home_ids
            if user_fixture.home_club_id == state.user_club_id
            else user_fixture.team_away_ids
        )
        ranked = sorted(
            ((pid, rating) for pid, rating in user_fixture.ratings.items() if pid in own_set),
            key=lambda item: -item[1],
        )[:5]
        for pid, rating in ranked:
            player = state.players.get(pid)
            top_performers.append({
                "name": player.full_name if player else pid,
                "rating": rating,
            })

    scoreline = None
    if user_fixture is not None and user_fixture.score:
        scoreline = f"{user_fixture.score[0]} - {user_fixture.score[1]}"

    summary = state.matchday_history[-1] if state.matchday_history else ""

    # Build chronological highlights for the user's match (goals / cards).
    # Used by the "Match highlights" animation on the frontend.
    highlights = []
    if user_fixture is not None and user_fixture.events:
        home_name = state.club(user_fixture.home_club_id).name
        away_name = state.club(user_fixture.away_club_id).name
        for ev in sorted(user_fixture.events, key=lambda e: (e.minute, 0)):
            player = state.players.get(ev.player_id)
            pname = player.full_name if player else ev.player_id
            if ev.club_id == user_fixture.home_club_id:
                team = home_name
            else:
                team = away_name
            # Running score revealed progressively during the animation.
            running_home = sum(
                1 for e in user_fixture.events
                if e.event_type == MatchEventType.GOAL
                and e.club_id == user_fixture.home_club_id
                and e.minute <= ev.minute
            )
            running_away = sum(
                1 for e in user_fixture.events
                if e.event_type == MatchEventType.GOAL
                and e.club_id == user_fixture.away_club_id
                and e.minute <= ev.minute
            )
            highlights.append({
                "minute": ev.minute,
                "type": ev.event_type,
                "player": pname,
                "team": team,
                "score": f"{running_home} - {running_away}",
            })
        # Cap so the animation stays snappy (~short list)
        highlights = highlights[:60]

    return {
        "role": "matchday",
        "week": week,
        "finished": outcome.get("finished", False),
        "user_had_match": user_fixture is not None,
        "scoreline": scoreline,
        "summary": summary,
        "results": results,
        "top_performers": top_performers,
        "highlights": highlights,
        "standings": standings_view(state),
    }


def cup_view(state: CareerState) -> dict:
    from manager.systems.cup import CUP_ID, ROUND_NAMES, cup_champion

    comp = state.competitions[CUP_ID]
    fixtures = sorted(
        (f for f in state.fixtures if f.season == state.current_season and f.competition_id == CUP_ID),
        key=lambda f: (f.week, f.id),
    )
    rounds = []
    for key, name in ROUND_NAMES.items():
        group = [f for f in fixtures if f.round == key]
        if not group and key != "round_of_16":
            continue
        rounds.append({
            "round": key,
            "label": name,
            "week": group[0].week if group else None,
            "ties": [
                {
                    "home": state.club(f.home_club_id).name,
                    "away": state.club(f.away_club_id).name,
                    "score": f"{f.home_goals} - {f.away_goals}" if f.score else "-",
                    "pens": f.resolved_by == "penalties",
                    "winner": f.winner_id,
                    "is_user": f.home_club_id == state.user_club_id or f.away_club_id == state.user_club_id,
                    "played": f.status.value == "played",
                }
                for f in group
            ],
        })
    champion = cup_champion(state)
    return {
        "role": "cup",
        "name": comp.name,
        "trophy": comp.trophy_name,
        "champion": state.club(champion).name if champion else None,
        "user_entered": True,
        "rounds": rounds,
    }


def clubs_view() -> dict:
    """Static manifest of every club in the league with logo paths and colours.

    The frontend uses this to render a small crest next to each club name
    (standings, fixtures, market, dashboard, news, transfer history) without
    every view having to repeat the club metadata.
    """
    from manager.data.clubs import CLUB_DEFS

    clubs = []
    for definition in sorted(CLUB_DEFS, key=lambda d: -d.reputation):
        clubs.append({
            "slug": definition.slug,
            "id": f"clb_{definition.slug}",
            "name": definition.name,
            "city": definition.city,
            "stadium": definition.stadium,
            "capacity": definition.capacity,
            "rep": definition.reputation,
            "primary": definition.primary,
            "secondary": definition.secondary,
            "logo": f"/logos/{definition.slug}.png",
        })
    return {"role": "clubs", "clubs": clubs}


def market_view(state: CareerState, q: str = "", position: str = "", kind: str = "") -> dict:
    club = state.user_club()
    qn = q.strip().lower()
    season_year = _season_year(state.current_season)
    from manager.systems.transfers import LOAN_MAX, starter_map, transfer_valuation_fee

    starters = starter_map(state)
    family = {
        "GK": {"GK"},
        "DF": {"LB", "CB", "RB", "WB"},
        "MF": {"DM", "CM", "AM", "LM", "RM"},
        "FW": {"LW", "RW", "CF", "ST"},
    }.get(position.strip().upper()) or ({position} if position else None)
    targets = []
    for player in state.players.values():
        if player.retired:
            continue
        if player.club_id == club.id:
            continue
        if family and str(player.preferred_position) not in family:
            continue
        age = player.age_as_of(season_year)
        if player.club_id is None:
            player_kind = "free"
        elif age <= 21:
            player_kind = "academy"
        else:
            player_kind = "first-team"
        loan = (
            player.club_id is not None
            and player.loaned_from is None
            and player.id not in starters.get(player.club_id, set())
        )
        if kind == "loan":
            if not loan:
                continue
        elif kind and player_kind != kind:
            continue
        seller = state.clubs.get(player.club_id) if player.club_id else None
        seller_name = seller.name if seller else "Free agent"
        if qn and qn not in player.full_name.lower() and qn not in seller_name.lower():
            continue
        targets.append({
            "id": player.id,
            "name": player.full_name,
            "club": seller_name,
            "position": str(player.preferred_position),
            "overall": player.overall,
            "age": age,
            "valuation": player.valuation,
            "wage": player.contract.weekly_wage if player.contract else 0,
            "contract_end": player.contract.end_season if player.contract else "",
            "free": player.club_id is None,
            "kind": player_kind,
            "loan": loan,
            "hint": transfer_valuation_fee(state, player, starters),
        })
    targets.sort(key=lambda t: (-t["overall"], t["age"], t["name"]))
    kinds = {"free": 0, "first-team": 0, "academy": 0}
    loan_available = 0
    for target in targets:
        kinds[target["kind"]] += 1
        if target["loan"]:
            loan_available += 1
    loans_in = [p for p in state.players.values() if p.club_id == club.id and p.loaned_from is not None]
    loans_out = [p for p in state.players.values() if p.loaned_from == club.id]
    from manager.systems.transfers import transfer_window, _generate_incoming_offers

    if transfer_window(state)["open"]:
        _generate_incoming_offers(state)
    window = transfer_window(state)
    offers = [
        {
            "id": o.id,
            "player": state.players[o.player_id].full_name if o.player_id in state.players else o.player_id,
            "player_id": o.player_id,
            "from": state.clubs[o.buyer_club_id].name,
            "fee": o.fee,
            "weekly_wage": o.weekly_wage,
            "years": o.contract_years,
            "status": o.status,
        }
        for o in state.incoming_offers
        if o.status == "pending"
    ]
    return {
        "role": "market",
        "window": window,
        "offers": offers,
        "budget": club.finances.transfer_budget,
        "wage_room": max(0, club.finances.weekly_wage_budget - club.finances.weekly_wage_spend),
        "total": len(targets),
        "kinds": kinds,
        "loan_available": loan_available,
        "loans": {
            "incoming": len(loans_in),
            "outgoing": len(loans_out),
            "max": LOAN_MAX,
            "room": LOAN_MAX - len(loans_in),
        },
        "targets": targets[:60],
        "renewals": renewal_view(state),
        "history": [
            {
                "id": t.id,
                "player": state.players[t.player_id].full_name if t.player_id in state.players else t.player_id,
                "from": state.clubs.get(t.from_club_id).name if t.from_club_id and t.from_club_id in state.clubs else "Free agent",
                "to": state.clubs.get(t.to_club_id).name if t.to_club_id and t.to_club_id in state.clubs else "",
                "fee": t.fee,
                "type": str(t.transfer_type),
                "status": str(t.status),
            }
            for t in state.transfers[-8:]
        ],
    }


def news_view(state: CareerState, category: str = "", limit: int = 40) -> dict:
    from manager.core.enums import NewsCategory

    articles = state.news
    if category:
        articles = [n for n in articles if str(n.category) == category]
    articles = sorted(articles, key=lambda n: (n.season, n.week, n.id))
    recent = list(reversed(articles[-limit:]))
    counts: dict[str, int] = {}
    for n in state.news:
        counts[str(n.category)] = counts.get(str(n.category), 0) + 1
    return {
        "role": "news",
        "category": category,
        "limit": limit,
        "total": len(state.news),
        "shown": len(recent),
        "counts": counts,
        "categories": [str(c) for c in NewsCategory],
        "articles": [
            {
                "id": n.id,
                "season": n.season,
                "week": n.week,
                "category": str(n.category),
                "headline": n.headline,
                "body": n.body,
                "clubs": [state.clubs[c].name for c in n.clubs_involved if c in state.clubs],
                "players": [state.players[p].full_name for p in n.players_involved if p in state.players],
            }
            for n in recent
        ],
    }


def renewal_view(state: CareerState) -> list[dict]:
    club = state.user_club()
    next_season = _shift_season(state.current_season, 1)
    season_year = _season_year(state.current_season)
    rows = []
    for pid in club.squad_ids:
        player = state.players.get(pid)
        if player is None:
            continue
        if player.loaned_from is not None:
            continue
        end = player.contract.end_season if player.contract else ""
        if end not in (state.current_season, next_season):
            continue
        wage = player.contract.weekly_wage if player.contract else 0
        rows.append({
            "id": player.id,
            "name": player.full_name,
            "position": str(player.preferred_position),
            "overall": player.overall,
            "age": player.age_as_of(season_year),
            "wage": wage,
            "end_season": end,
            "suggested": int(wage * 1.05),
        })
    rows.sort(key=lambda r: -r["overall"])
    return rows[:15]


def _shift_season(season_id: str, years: int) -> str:
    base = int(season_id.split("-")[0])
    return f"{base + years}-{str(base + years + 1)[2:]}"