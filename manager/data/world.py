"""World construction.

Builds the complete fictional database for a season: clubs, squads, free
agents, AI managers, and competitions. Output is deterministic for a seed,
which is what makes careers reproducible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from manager.core.enums import CompetitionType, Position
from manager.core.models import (
    Club,
    ClubFinances,
    Competition,
    Manager,
    Tactics,
)
from manager.data import names
from manager.data.clubs import CLUB_DEFS
from manager.data.players import generate_free_agents, generate_squad
from manager.data.renames import apply_custom_names, load_custom_names
from manager.rng import SeededRng

DB_VERSION = 1
DEFAULT_SEASON_ID = "2026-27"
DEFAULT_SEASON_YEAR = 2026

FORMATION_POOL = ["4-3-3", "4-4-2", "4-2-3-1", "3-5-2", "5-3-2", "4-3-2-1", "3-4-3", "4-1-4-1"]


@dataclass
class DatabaseWorld:
    version: int
    season_id: str
    season_name: str
    season_year: int
    clubs: list[Club] = field(default_factory=list)
    players: list = field(default_factory=list)
    competitions: list[Competition] = field(default_factory=list)
    managers: list[Manager] = field(default_factory=list)

    @property
    def club_map(self) -> dict[str, Club]:
        return {club.id: club for club in self.clubs}

    @property
    def player_map(self) -> dict:
        return {player.id: player for player in self.players}


def _ai_manager(club_id: str, rng: SeededRng) -> Manager:
    first, last = names.full_name(rng)
    tactics = Tactics(formation=rng.choice(FORMATION_POOL, stream="ai_tactics"))
    end_year = rng.randint(2027, 2029, "mgr_contract")
    return Manager(
        id=f"mgr_{club_id}",
        first_name=first,
        last_name=last,
        nationality=names.nationality(rng),
        age=rng.randint(38, 62, "mgr_age"),
        reputation=rng.randint(40, 92, "mgr_rep"),
        tactics=tactics,
        club_id=club_id,
        contract_end_season=f"{end_year}-{str(end_year + 1)[2:]}",
    )


def _league_rounds(club_count: int) -> int:
    return 2 * (club_count - 1)


def build_world(
    seed: int = 42,
    season_id: str = DEFAULT_SEASON_ID,
    season_year: int = DEFAULT_SEASON_YEAR,
    names_file: str | Path | None = None,
) -> DatabaseWorld:
    """Generate a fresh fictional football universe."""
    rng = SeededRng(seed)
    clubs = []
    all_players = []

    for definition in CLUB_DEFS:
        club_id = f"clb_{definition.slug}"
        squad = generate_squad(club_id, definition.reputation, season_id, season_year, rng)
        all_players.extend(squad)

        total_wages = sum(p.contract.weekly_wage for p in squad if p.contract)
        weekly_wage_budget = clamp_int(int(total_wages * 1.22), 1, 10 ** 7)

        sponsorship = int(1_800_000 * math.exp((definition.reputation - 55) / 14))
        tickets = definition.capacity * 380
        balance = sponsorship + tickets
        transfer_budget = int(
            2_500_000 * math.exp((definition.reputation - 55) / 11)
        ) + rng.randint(0, 400_000, "budgets")

        club = Club(
            id=club_id,
            name=definition.name,
            city=definition.city,
            nation="Valland",
            stadium_name=definition.stadium,
            capacity=definition.capacity,
            primary_color=definition.primary,
            secondary_color=definition.secondary,
            reputation=definition.reputation,
            finances=ClubFinances(
                balance=balance,
                transfer_budget=transfer_budget,
                weekly_wage_budget=weekly_wage_budget,
                weekly_wage_spend=total_wages,
                sponsor_yearly_income=sponsorship,
                ticket_yearly_income=tickets,
            ),
            tactics=Tactics(formation=rng.choice(FORMATION_POOL, stream="club_tactics")),
            squad_ids=[p.id for p in squad],
            founded_year=definition.founded,
        )
        club.manager_id = f"mgr_{club_id}"
        clubs.append(club)

    managers = []
    for club in clubs:
        manager = _ai_manager(club.id, rng)
        managers.append(manager)

    free_agents = generate_free_agents(42, season_year, rng)
    gk_free = any(p.preferred_position == Position.GK for p in free_agents)
    if not gk_free:
        all_players.append(free_agents[0])

    all_players.extend(free_agents)

    club_ids = [club.id for club in clubs]
    apex = Competition(
        id="apex_division",
        name="Super League",
        comp_type=CompetitionType.LEAGUE,
        nation="Valland",
        tier=1,
        club_ids=list(club_ids),
        params={"rounds": _league_rounds(len(club_ids))},
        trophy_name="Super League Trophy",
    )
    cup = Competition(
        id="presidents_cup",
        name="Presidents' Cup",
        comp_type=CompetitionType.CUP,
        nation="Valland",
        tier=1,
        club_ids=list(club_ids),
        params={"rounds": ["Group", "Round of 16"]},
        trophy_name="Presidents' Cup",
    )

    world = DatabaseWorld(
        version=DB_VERSION,
        season_id=season_id,
        season_name=f"{season_year}/{season_year + 1}",
        season_year=season_year,
        clubs=clubs,
        players=all_players,
        competitions=[apex, cup],
        managers=managers,
    )

    if names_file is not None:
        overrides = load_custom_names(names_file)
        warnings = apply_custom_names(world, overrides)
        for warning in warnings:
            print(f"[custom names] {warning}")

    return world


def clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


@lru_cache(maxsize=8)
def cached_world(seed: int, names_file: str | Path | None = None) -> DatabaseWorld:
    """Memoised world build so repeated queries reuse one generation."""
    if names_file is None:
        from manager.data.renames import DEFAULT_NAMES_FILE

        names_file = DEFAULT_NAMES_FILE if DEFAULT_NAMES_FILE.is_file() else None
    return build_world(seed, names_file=names_file)