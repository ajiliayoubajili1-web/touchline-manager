"""Player and squad generation.

Creates a realistic, fictional squad for every club plus a pool of free agents.
Quality scales with club reputation; every generation is deterministic for a
given seed.
"""

from __future__ import annotations

from datetime import date

from manager.core.enums import PersonalityTrait, Position
from manager.core.models import Attributes, Contract, Player
from manager.core.ratings import ATTRIBUTE_NAMES, overall_rating, position_weights
from manager.core.validate import clamp
from manager.core.valuation import market_value, wage_for_overall
from manager.data import names
from manager.rng import SeededRng

SQUAD_TEMPLATE = [
    ("GK", 3),
    ("CB", 4),
    ("FB", 4),
    ("DM", 2),
    ("CM", 4),
    ("AM", 2),
    ("W", 3),
    ("ST", 3),
]

TRAIT_WEIGHTS = {
    PersonalityTrait.PROFESSIONAL: 0.30,
    PersonalityTrait.AMBITIOUS: 0.25,
    PersonalityTrait.LOYAL: 0.20,
    PersonalityTrait.DEMANDING: 0.15,
    PersonalityTrait.CALM: 0.20,
    PersonalityTrait.COMPETITIVE: 0.30,
    PersonalityTrait.CONFIDENT: 0.20,
    PersonalityTrait.EASYGOING: 0.15,
    PersonalityTrait.PERFECTIONIST: 0.08,
    PersonalityTrait.DETERMINED: 0.20,
    PersonalityTrait.ECCENTRIC: 0.05,
}

TRAITS = list(TRAIT_WEIGHTS.keys())
TRAIT_CHANCES = list(TRAIT_WEIGHTS.values())

BAND_AGES = {"prospect": (16, 20), "core": (21, 28), "veteran": (29, 34)}


def average_overall(reputation: int) -> int:
    return clamp(int(round(36 + reputation * 0.44)), 40, 88)


class Band:
    PROSPECT = "prospect"
    CORE = "core"
    VETERAN = "veteran"


def _attributes_for(position: Position, target: int, rng: SeededRng) -> Attributes:
    weights = position_weights(position)
    values = {}
    for name in ATTRIBUTE_NAMES:
        w = weights.get(name, 0.0)
        spread = 1.0 - w * 0.55
        raw = target + rng.gauss(0.0, 9.0 * spread, "attributes")
        raw += (1.0 - w) * rng.gauss(0.0, 5.0, "attributes")
        values[name] = clamp(int(round(raw)), 1, 99)
    return Attributes(**values)


def _personality(rng: SeededRng) -> list[PersonalityTrait]:
    traits = set(rng.choices(TRAITS, weights=TRAIT_CHANCES, k=2, stream="personality"))
    if rng.random("personality") < 0.30:
        traits.add(rng.choice(TRAITS, stream="personality"))
    return sorted(traits, key=lambda t: t.value)


def _next_season(season_id: str, steps: int) -> str:
    start = int(season_id.split("-")[0])
    end = start + 1
    for _ in range(steps):
        start += 1
        end += 1
    return f"{start}-{str(end)[2:]}"


def _positions_for(role: str, rng: SeededRng) -> tuple[Position, list[Position]]:
    pool = names.POSITION_POOLS[role]
    primary = Position(rng.choice(pool, stream="positions"))
    alternates = [Position(p) for p in pool if p != primary.value]
    positions = [primary]
    if rng.random("positions") < names.ALT_POSITION_WEIGHT and len(alternates) >= 2:
        positions.append(alternates[rng.randint(0, len(alternates) - 1, "positions")])
    elif rng.random("positions") < 0.5 and alternates:
        positions.append(alternates[0])
    return primary, positions


def _assign_band(rng: SeededRng, index: int) -> str:
    if index < 3:
        return Band.PROSPECT
    if rng.random("bands") < 0.12:
        return Band.VETERAN
    return Band.CORE


def _overall_for(rep: int, band: str, rng: SeededRng, star_bonus: bool) -> int:
    avg = average_overall(rep)
    if band == Band.PROSPECT:
        target = avg - 16 + rng.gauss(0, 5, "overall")
        return clamp(int(round(target)), 35, avg - 2)
    if band == Band.VETERAN:
        target = avg - 5 + rng.gauss(0, 4, "overall")
        return clamp(int(round(target)), 42, avg + 3)
    bonus = 7 if star_bonus else 0
    target = avg + bonus + rng.gauss(0, 4, "overall")
    return clamp(int(round(target)), 40, 90)


def _potential_for(band: str, overall: int, rng: SeededRng) -> int:
    if band == Band.PROSPECT:
        room = rng.randint(12, 26, "potential")
    elif band == Band.CORE:
        room = rng.randint(2, 10, "potential")
    else:
        room = rng.randint(0, 4, "potential")
    potential = overall + room
    if band == Band.PROSPECT and rng.random("potential") < 0.12:
        potential += rng.randint(2, 5, "potential")
    return clamp(potential, overall, 99)


def _birthday(age: int, season_start_year: int, rng: SeededRng) -> date:
    month = rng.randint(1, 12, "birthday")
    day = rng.randint(1, 28, "birthday")
    return date(season_start_year - age, month, day)


def _make_player(
    player_id: str,
    club_id: str | None,
    role: str,
    rep: int,
    band: str,
    season_start_year: int,
    rng: SeededRng,
    star_bonus: bool = False,
    age_override: int | None = None,
) -> Player:
    first, last = names.full_name(rng)
    nation = names.nationality(rng)
    primary, positions = _positions_for(role, rng)
    overall_target = _overall_for(rep, band, rng, star_bonus)
    attributes = _attributes_for(primary, overall_target, rng)
    overall = overall_rating(attributes, primary)
    potential = _potential_for(band, overall, rng)
    if age_override is not None:
        age = age_override
    else:
        low, high = BAND_AGES[band]
        age = rng.randint(low, high, "age")
    valuation = market_value(overall, age, potential)
    birth = _birthday(age, season_start_year, rng)

    return Player(
        id=player_id,
        first_name=first,
        last_name=last,
        nationality=nation,
        date_of_birth=birth,
        positions=positions,
        preferred_position=primary,
        attributes=attributes,
        potential=potential,
        personality=_personality(rng),
        club_id=club_id,
        valuation=valuation,
        two_footedness=rng.randint(1, 5, "footedness"),
        flair=rng.randint(1, 5, "flair"),
    )


def generate_squad(
    club_id: str,
    rep: int,
    season_id: str,
    season_start_year: int,
    rng: SeededRng,
) -> list[Player]:
    """Generate a full squad for a club and attach contracts."""

    players = []
    used_numbers = set()
    star_indices = set()

    if rep >= 90:
        pool = range(len(SQUAD_TEMPLATE) * SQUAD_TEMPLATE[0][1])
        star_indices.update(rng.sample(list(pool), min(2, len(pool)), "stars"))

    index = 0
    for role, count in SQUAD_TEMPLATE:
        for _ in range(count):
            band = _assign_band(rng, index)
            number = None
            while number is None or number in used_numbers:
                number = rng.randint(1, 31, "numbers")
            used_numbers.add(number)

            player_id = f"{club_id.replace('-', '_')}_{index:02d}"
            boon = index in star_indices
            player = _make_player(
                player_id, club_id, role, rep, band, season_start_year, rng,
                star_bonus=boon,
            )
            wage = wage_for_overall(player.overall)
            contract_years = rng.randint(2, 4, "contract_years")
            player.contract = Contract(
                player_id=player.id,
                club_id=club_id,
                weekly_wage=wage,
                start_season=season_id,
                end_season=_next_season(season_id, contract_years - 1),
                squad_number=number,
            )
            players.append(player)
            index += 1
    return players


def generate_free_agents(
    count: int,
    season_start_year: int,
    rng: SeededRng,
) -> list[Player]:
    """Generate unattached players available on the free market."""
    roles = ["GK", "CB", "FB", "DM", "CM", "AM", "W", "ST"]
    players = []
    for i in range(count):
        role = roles[rng.randint(0, len(roles) - 1, "fa_role")]
        rep = rng.randint(52, 84, "fa_rep")
        age = rng.randint(19, 31, "fa_age")
        band = Band.PROSPECT if age <= 23 else (Band.CORE if age <= 28 else Band.VETERAN)
        player = _make_player(
            f"fa_{i:03d}", None, role, rep, band, season_start_year, rng,
            age_override=age,
        )
        players.append(player)
    return players