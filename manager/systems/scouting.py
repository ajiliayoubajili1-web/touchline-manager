"""Academy and scouting systems.

Every club runs a youth academy (a full 11-player XI, one player per slot).
The user can promote academy players into the first-team squad (hard cap 40) or
move young first-team players back down. Scouts are hired staff: each assigned a
scouting region, they find hidden young talent around the world automatically
every few weeks (and on demand via a "Search" button). Discoveries can then be
signed into the academy or straight into the first team for a fee.
"""

from __future__ import annotations

from manager.core.enums import NewsCategory
from manager.core.models import Contract, Discovery, NewsArticle, Player, Scout
from manager.core.validate import clamp
from manager.core.valuation import wage_for_overall
from manager.data import names
from manager.data.players import _make_player
from manager.rng import SeededRng

ACADEMY_POSITIONS = ["GK", "CB", "CB", "FB", "FB", "DM", "CM", "CM", "AM", "W", "ST"]
ACADEMY_SIZE = len(ACADEMY_POSITIONS)  # 11: one full XI per club
ACADEMY_HARD_CAP = 16  # an academy can grow a little beyond the starting XI
MAX_SQUAD_SIZE = 40  # hard cap on the first-team squad (promotion stops here)
MAX_SCOUTS = 3
DISCOVERY_LIFETIME_WEEKS = 8
MAX_CONCURRENT_DISCOVERIES = 6

REGIONS = [
    "Europe",
    "South America",
    "Africa",
    "Asia",
    "North America",
    "Worldwide",
]

REGION_NATIONS: dict[str, list[str]] = {
    "Europe": ["France", "Spain", "England", "Germany", "Netherlands", "Italy", "Portugal"],
    "South America": ["Brazil", "Argentina"],
    "Africa": ["Tunisia"],
    "Asia": [],
    "North America": [],
    "Worldwide": list(names.NATIONS),
}

_position_weights = {
    "GK": 0.8, "CB": 1.4, "FB": 1.2, "DM": 1.2,
    "CM": 1.5, "AM": 1.1, "W": 1.3, "ST": 1.3,
}


class ScoutingError(Exception):
    pass


def _season_year(season_id: str) -> int:
    try:
        return int(season_id.split("-")[0])
    except (ValueError, AttributeError):
        return 2026


def _next_season(season_id: str, steps: int = 3) -> str:
    start = int(season_id.split("-")[0])
    return f"{start + steps}-{str(start + steps + 1)[2:]}"


def _contract(player_id: str, club_id: str, overall: int, season_id: str, wage: int | None = None) -> Contract:
    return Contract(
        player_id=player_id,
        club_id=club_id,
        weekly_wage=wage if wage is not None else wage_for_overall(overall),
        start_season=season_id,
        end_season=_next_season(season_id),
    )


def _news(state, week: int, category: NewsCategory, headline: str, body: str,
          player_id: str | None = None, club_id: str | None = None) -> None:
    anchor = player_id or club_id or "academy"
    article = NewsArticle(
        id=f"news_{state.current_season}_w{week}_{anchor}",
        season=state.current_season,
        week=week,
        category=category,
        headline=headline,
        body=body,
        clubs_involved=[club_id] if club_id else [],
        players_involved=[player_id] if player_id else [],
    )
    if all(a.id != article.id for a in state.news):
        state.news.append(article)
    state.news = state.news[-80:]


def _stable_hash(text: str) -> int:
    value = 0
    for ch in text:
        value = (value * 31 + ord(ch)) & 0xFFFFFFFF
    return value


def _role_roll(rng: SeededRng) -> str:
    roles = list(_position_weights)
    return rng.choices(roles, weights=[_position_weights[r] for r in roles], k=1, stream="disc_role")[0]


def _nations_for_region(region: str) -> list[str]:
    pool = REGION_NATIONS.get(region) or list(names.NATIONS)
    return pool or list(names.NATIONS)


def _region_nationality(region: str, rng: SeededRng) -> str:
    return rng.choice(_nations_for_region(region), stream="discovery_nat")


def _discovery_player(state, discovery: Discovery) -> Player:
    """Deterministically build the discovered talent (used for view AND signing)."""
    rng = SeededRng(state.seed ^ _stable_hash(discovery.player_id))
    year = _season_year(state.current_season)
    age = rng.randint(15, 19, f"disc_age_{discovery.id}")
    club = state.user_club()
    rep = clamp(club.reputation + 10, 55, 95)
    player = _make_player(
        discovery.player_id, None, _role_roll(rng), rep, "prospect", year, rng,
        age_override=age,
    )
    player.nationality = _region_nationality(discovery.region, rng)
    return player


# ---------------------------------------------------------------------------
# Academy rosters
# ---------------------------------------------------------------------------

def ensure_academies(state, rng: SeededRng | None = None) -> None:
    """Create a full 11-player academy XI for every club (idempotent)."""
    if state.academy:
        return
    rng = rng or SeededRng(state.seed ^ 0xACE7A)
    year = _season_year(state.current_season)
    for club in state.clubs.values():
        roster = []
        for index, role in enumerate(ACADEMY_POSITIONS):
            player_id = f"{club.id.replace('-', '_')}_aca_{index:02d}"
            if player_id in state.players:
                roster.append(player_id)
                continue
            age = rng.randint(15, 18, f"aca_age_{club.id}_{index}")
            player = _make_player(
                player_id, club.id, role, club.reputation, "prospect", year, rng,
                age_override=age,
            )
            player.contract = _contract(player_id, club.id, player.overall, state.current_season)
            state.players[player_id] = player
            roster.append(player_id)
        if not state.academy.get(club.id):
            state.academy[club.id] = roster


def academy_roster(state, club_id: str) -> list[str]:
    return list(state.academy.get(club_id) or [])


def promote_to_first_team(state, player_id: str) -> Player:
    """Move an academy player into the first-team squad (hard cap 40)."""
    club = state.user_club()
    roster = academy_roster(state, club.id)
    if player_id not in roster:
        raise ScoutingError("that player is not in your academy")
    if player_id in club.squad_ids:
        raise ScoutingError("that player is already in the first team")
    if len(club.squad_ids) >= MAX_SQUAD_SIZE:
        raise ScoutingError(f"your first team is full ({MAX_SQUAD_SIZE}/{MAX_SQUAD_SIZE}) - sell or release someone first")

    player = state.players[player_id]
    roster.remove(player_id)
    state.academy[club.id] = roster
    club.squad_ids.append(player_id)
    if player.contract is None:
        player.contract = _contract(player_id, club.id, player.overall, state.current_season)

    _news(
        state, state.current_week, NewsCategory.YOUNG_STAR,
        f"{player.full_name} promoted to the first team",
        f"{club.name} gave academy talent {player.full_name} (age {player.age_as_of(_season_year(state.current_season))}) their first-team chance.",
        player_id=player_id, club_id=club.id,
    )
    return player


def demote_to_academy(state, player_id: str) -> Player:
    """Move a young first-team player back down to the academy (max age 21)."""
    club = state.user_club()
    if player_id not in club.squad_ids:
        raise ScoutingError("that player is not in your first team")
    player = state.players[player_id]
    age = player.age_as_of(_season_year(state.current_season))
    if age > 21:
        raise ScoutingError("only young players (21 or under) can move back to the academy")
    if len(club.squad_ids) <= 15:
        raise ScoutingError("your first team would be too small - keep at least 16 players")
    roster = academy_roster(state, club.id)
    if len(roster) >= ACADEMY_HARD_CAP:
        raise ScoutingError("your academy is full - promote someone first")

    club.squad_ids.remove(player_id)
    roster.append(player_id)
    state.academy[club.id] = roster

    _news(
        state, state.current_week, NewsCategory.YOUNG_STAR,
        f"{player.full_name} moved back to the academy",
        f"{club.name} sent {player.full_name} back to the academy for more development time.",
        player_id=player_id, club_id=club.id,
    )
    return player


# ---------------------------------------------------------------------------
# Scouts
# ---------------------------------------------------------------------------

def scouts_for(state, club_id: str) -> list[Scout]:
    return list(state.scouts.get(club_id) or [])


def can_hire_scout(state) -> bool:
    return len(scouts_for(state, state.user_club_id)) < MAX_SCOUTS


def hire_scout(state, rng: SeededRng | None = None) -> Scout:
    """Recruit a new scout for the user's club (max 3 at once)."""
    club = state.user_club()
    if not can_hire_scout(state):
        raise ScoutingError(f"you can only have {MAX_SCOUTS} scouts at once")
    rng = rng or SeededRng(state.seed ^ len(scouts_for(state, club.id)) ^ 0x5C0E7)
    first, last = names.full_name(rng, stream="scout_names")
    rating = clamp(club.reputation // 6 + 50 + rng.randint(-4, 4, "scout_rating"), 55, 92)
    fee = rating * 15_000
    if club.finances.balance < fee:
        raise ScoutingError("your club cannot afford to hire another scout")
    club.finances.balance -= fee

    scout = Scout(
        id=f"scout_{club.id}_{len(scouts_for(state, club.id)):02d}",
        first_name=first,
        last_name=last,
        nationality=names.nationality(rng, stream="scout_nat"),
        region=rng.choice(REGIONS, stream="scout_region"),
        rating=rating,
        weekly_wage=rating * 900,
        hired_week=state.current_week,
        next_discovery_week=state.current_week + 2,
    )
    state.scouts.setdefault(club.id, []).append(scout)

    _news(
        state, state.current_week, NewsCategory.FINANCE,
        f"Scout {scout.full_name} joins the club",
        f"{club.name} hired {scout.full_name} ({scout.nationality}) to scout {scout.region} for the academy.",
        club_id=club.id,
    )
    return scout


def fire_scout(state, scout_id: str) -> None:
    club = state.user_club()
    roster = scouts_for(state, club.id)
    scout = next((s for s in roster if s.id == scout_id), None)
    if scout is None:
        raise ScoutingError("unknown scout")
    roster.remove(scout)
    state.scouts[club.id] = roster


def _discovery_interval(scout: Scout) -> int:
    return max(3, 9 - scout.rating // 15)


def _generate_discovery(state, scout: Scout, week: int) -> Discovery:
    """Register a hidden young talent as an offer for the club."""
    club = state.user_club()
    seq = len(state.discoveries.get(club.id) or [])
    discovery = Discovery(
        id=f"disc_{club.id}_{week}_{seq}",
        player_id=f"{club.id.replace('-', '_')}_disc_{week}_{seq}",
        scout_id=scout.id,
        club_id=club.id,
        region=scout.region,
        found_week=week,
        expires_week=week + DISCOVERY_LIFETIME_WEEKS,
        signing_fee=0,
    )
    player = _discovery_player(state, discovery)
    discovery.signing_fee = max(500_000, min(6_000_000, player.potential * 25_000))
    state.discoveries.setdefault(club.id, []).append(discovery)
    return discovery


def _scout_pay(state, scout: Scout) -> None:
    club = state.user_club()
    club.finances.balance = max(0, club.finances.balance - scout.weekly_wage)


def process_scouting(state, week: int) -> None:
    """Weekly scout payroll, automatic discoveries, and discovery expiry."""
    club = state.user_club()
    for scout in scouts_for(state, club.id):
        _scout_pay(state, scout)
        if week >= scout.next_discovery_week:
            pending = len(state.discoveries.get(club.id) or [])
            if pending < MAX_CONCURRENT_DISCOVERIES:
                _generate_discovery(state, scout, week)
                scout.next_discovery_week = week + _discovery_interval(scout)
            else:
                scout.next_discovery_week = week + 1

    live: list[Discovery] = []
    for discovery in state.discoveries.get(club.id) or []:
        if discovery.expires_week >= week:
            live.append(discovery)
    state.discoveries[club.id] = live


def search_now(state) -> list[Discovery]:
    """An on-demand scout sweep: every scout immediately finds something new."""
    club = state.user_club()
    roster = scouts_for(state, club.id)
    if not roster:
        raise ScoutingError("you have no scouts - hire one first")
    found = []
    pending = len(state.discoveries.get(club.id) or [])
    for scout in roster:
        if pending >= MAX_CONCURRENT_DISCOVERIES:
            break
        discovery = _generate_discovery(state, scout, state.current_week)
        found.append(discovery)
        pending += 1
        scout.next_discovery_week = state.current_week + 1
    if not found:
        raise ScoutingError("too many pending discoveries - sign or wait for some to expire")
    return found


# ---------------------------------------------------------------------------
# Signing discoveries
# ---------------------------------------------------------------------------

def sign_discovery(state, discovery_id: str, target: str) -> Player:
    """Sign a discovered talent into the academy (default) or the first team."""
    club = state.user_club()
    if target not in ("academy", "first_team"):
        raise ScoutingError("target must be 'academy' or 'first_team'")
    if target == "first_team" and len(club.squad_ids) >= MAX_SQUAD_SIZE:
        raise ScoutingError(f"your first team is full ({MAX_SQUAD_SIZE}/{MAX_SQUAD_SIZE})")
    if target == "academy" and len(academy_roster(state, club.id)) >= ACADEMY_HARD_CAP:
        raise ScoutingError(f"your academy is full ({ACADEMY_HARD_CAP}/{ACADEMY_HARD_CAP})")

    pending = state.discoveries.get(club.id) or []
    discovery = next((d for d in pending if d.id == discovery_id), None)
    if discovery is None:
        raise ScoutingError("unknown discovery")
    if discovery.expires_week < state.current_week:
        raise ScoutingError("that discovery has expired - the trail went cold")
    if discovery.club_id != club.id:
        raise ScoutingError("that discovery does not belong to your club")
    if club.finances.transfer_budget < discovery.signing_fee:
        raise ScoutingError(
            f"not enough transfer budget ({discovery.signing_fee:,} needed, "
            f"{club.finances.transfer_budget:,} available)"
        )

    player = _discovery_player(state, discovery)
    player.club_id = club.id
    player.contract = _contract(player.id, club.id, player.overall, state.current_season)
    state.players[player.id] = player
    club.finances.transfer_budget -= discovery.signing_fee
    pending.remove(discovery)
    state.discoveries[club.id] = pending

    where = "first team" if target == "first_team" else "academy"
    if target == "first_team":
        club.squad_ids.append(player.id)
    else:
        state.academy.setdefault(club.id, []).append(player.id)

    scout = next((s for s in scouts_for(state, club.id) if s.id == discovery.scout_id), None)
    scout_label = f"scout {scout.full_name}" if scout else "the scouting team"
    _news(
        state, state.current_week, NewsCategory.YOUNG_STAR,
        f"{player.full_name} signs for {club.name}",
        f"Discovered by {scout_label} in {discovery.region}, {player.full_name} ({player.age_as_of(_season_year(state.current_season))}) joined the {where}.",
        player_id=player.id, club_id=club.id,
    )
    return player