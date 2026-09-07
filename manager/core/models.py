"""Core domain models.

Every object in the game is a plain dataclass so it can be dumped to and
reloaded from structured JSON (see :mod:`manager.core.serialization`). Models
store data; behaviour lives in the core services, the simulation systems, and
the API layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from manager.core.enums import (
    AttackingApproach,
    CompetitionType,
    DefensiveApproach,
    DefensiveLine,
    Difficulty,
    FixtureStatus,
    MatchEventType,
    Mentality,
    NewsCategory,
    PassingStyle,
    PersonalityTrait,
    PlayingStyle,
    Position,
    PressingIntensity,
    Tempo,
    TacticalDuty,
    TrainingFocus,
    TrainingIntensity,
    TransferStatus,
    TransferType,
)
from manager.core.ratings import overall_rating


@dataclass
class Attributes:
    pace: int
    shooting: int
    passing: int
    dribbling: int
    defending: int
    physical: int
    goalkeeper: int

    def __post_init__(self) -> None:
        for name in ("pace", "shooting", "passing", "dribbling", "defending", "physical", "goalkeeper"):
            value = int(getattr(self, name))
            setattr(self, name, max(1, min(99, value)))


@dataclass
class Injury:
    injury_type: str
    weeks_remaining: int
    description: str

    def __post_init__(self) -> None:
        self.weeks_remaining = max(0, int(self.weeks_remaining))


@dataclass
class Suspension:
    matches_remaining: int
    reason: str

    def __post_init__(self) -> None:
        self.matches_remaining = max(0, int(self.matches_remaining))


@dataclass
class Contract:
    player_id: str
    club_id: str
    weekly_wage: int
    start_season: str
    end_season: str
    release_clause: int | None = None
    squad_number: int | None = None

    def __post_init__(self) -> None:
        self.weekly_wage = max(0, int(self.weekly_wage))


@dataclass
class PlayerSeasonStats:
    season: str
    appearances: int = 0
    starts: int = 0
    goals: int = 0
    assists: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    minutes_played: int = 0
    clean_sheets: int = 0
    goals_conceded: int = 0
    average_rating: float = 0.0
    ratings_count: int = 0


@dataclass
class DevelopmentRecord:
    season: str
    applied_at: str
    attribute_growth: dict[str, int] = field(default_factory=dict)
    overall_before: int = 0
    overall_after: int = 0
    note: str = ""


@dataclass
class Player:
    id: str
    first_name: str
    last_name: str
    nationality: str
    date_of_birth: date
    positions: list[Position]
    preferred_position: Position
    attributes: Attributes
    potential: int
    personality: list[PersonalityTrait] = field(default_factory=list)
    club_id: str | None = None
    contract: Contract | None = None
    morale: int = 70
    form: int = 65
    fitness: int = 95
    energy: int = 100
    injury: Injury | None = None
    suspension: Suspension | None = None
    valuation: int = 0
    two_footedness: int = 3
    flair: int = 3
    career_appearances: int = 0
    career_goals: int = 0
    career_assists: int = 0
    season_stats: list[PlayerSeasonStats] = field(default_factory=list)
    development_history: list[DevelopmentRecord] = field(default_factory=list)
    training_focus: TrainingFocus = TrainingFocus.GENERAL
    training_intensity: TrainingIntensity = TrainingIntensity.NORMAL
    tactical_role: str = "standard"
    tactical_duty: TacticalDuty = TacticalDuty.SUPPORT
    retired: bool = False
    loaned_from: str | None = None

    def __post_init__(self) -> None:
        self.potential = max(1, min(99, int(self.potential)))
        self.morale = max(0, min(100, int(self.morale)))
        self.form = max(0, min(100, int(self.form)))
        self.fitness = max(0, min(100, int(self.fitness)))
        self.energy = max(0, min(100, int(self.energy)))

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part)

    @property
    def overall(self) -> int:
        return overall_rating(self.attributes, self.preferred_position)

    def rating_at(self, position: Position) -> int:
        return overall_rating(self.attributes, position)

    def age_as_of(self, year: int) -> int:
        born = self.date_of_birth
        return year - born.year - ((born.month, born.day) > (6, 30))


@dataclass
class ClubFinances:
    balance: int
    transfer_budget: int
    weekly_wage_budget: int
    weekly_wage_spend: int = 0
    sponsor_yearly_income: int = 0
    ticket_yearly_income: int = 0
    prize_yearly_income: int = 0

    def __post_init__(self) -> None:
        for name in ("balance", "transfer_budget", "weekly_wage_budget", "weekly_wage_spend",
                     "sponsor_yearly_income", "ticket_yearly_income", "prize_yearly_income"):
            setattr(self, name, max(0, int(getattr(self, name))))


@dataclass
class BoardConfidence:
    overall: int = 70
    results: int = 70
    finances: int = 70
    transfers: int = 70

    def __post_init__(self) -> None:
        for name in ("overall", "results", "finances", "transfers"):
            setattr(self, name, max(0, min(100, int(getattr(self, name)))))


@dataclass
class ClubObjective:
    objective_id: str
    label: str
    target: dict[str, object] = field(default_factory=dict)
    reward: int = 0
    season: str = ""
    achieved: bool = False

    def met(self, context: dict) -> bool:
        target_type = self.target.get("type")
        if target_type == "league_position":
            return context.get("league_position", 999) is not None and context["league_position"] <= self.target.get("finish_at_most", 999)
        if target_type == "cup_round":
            return context.get("cup_round_reached", 0) >= self.target.get("round", 0)
        return False


@dataclass
class Tactics:
    formation: str = "4-3-3"
    mentality: Mentality = Mentality.BALANCED
    playing_style: PlayingStyle = PlayingStyle.BALANCED
    pressing: PressingIntensity = PressingIntensity.MEDIUM
    passing: PassingStyle = PassingStyle.MIXED
    tempo: Tempo = Tempo.NORMAL
    defensive_line: DefensiveLine = DefensiveLine.NORMAL
    defensive_approach: DefensiveApproach = DefensiveApproach.BALANCED
    attacking_approach: AttackingApproach = AttackingApproach.BALANCED


@dataclass
class Manager:
    id: str
    first_name: str
    last_name: str
    nationality: str
    age: int
    reputation: int
    tactics: Tactics
    club_id: str | None = None
    is_user: bool = False
    contract_end_season: str | None = None
    trophy_count: int = 0
    preferred_positions: list[Position] = field(default_factory=list)
    favourite_coach: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


@dataclass
class Club:
    id: str
    name: str
    city: str
    nation: str
    stadium_name: str
    capacity: int
    primary_color: str
    secondary_color: str
    reputation: int
    finances: ClubFinances
    tactics: Tactics = field(default_factory=Tactics)
    manager_id: str | None = None
    board: BoardConfidence = field(default_factory=BoardConfidence)
    objectives: list[ClubObjective] = field(default_factory=list)
    squad_ids: list[str] = field(default_factory=list)
    formation_lineup: list[str] = field(default_factory=list)
    trophy_history: list[str] = field(default_factory=list)
    founded_year: int = 1900

    def __post_init__(self) -> None:
        self.reputation = max(1, min(100, int(self.reputation)))


@dataclass
class Standings:
    club_id: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against


@dataclass
class MatchEvent:
    minute: int
    club_id: str
    player_id: str
    event_type: MatchEventType
    secondary_player_id: str | None = None
    minute_codes: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.minute = max(1, min(120, int(self.minute)))


@dataclass
class MatchStats:
    possession_home: float = 50.0
    possession_away: float = 50.0
    shots_home: int = 0
    shots_away: int = 0
    shots_on_target_home: int = 0
    shots_on_target_away: int = 0
    corners_home: int = 0
    corners_away: int = 0
    fouls_home: int = 0
    fouls_away: int = 0
    expected_goals_home: float = 0.0
    expected_goals_away: float = 0.0


@dataclass
class Fixture:
    id: str
    season: str
    competition_id: str
    week: int
    home_club_id: str
    away_club_id: str
    team_home_ids: list[str] = field(default_factory=list)
    team_away_ids: list[str] = field(default_factory=list)
    home_goals: int | None = None
    away_goals: int | None = None
    status: FixtureStatus = FixtureStatus.SCHEDULED
    date: str = ""
    events: list[MatchEvent] = field(default_factory=list)
    stats: MatchStats | None = None
    ratings: dict[str, float] = field(default_factory=dict)
    attendance: int = 0
    is_user_match: bool = False
    round: str = ""
    winner_id: str | None = None
    resolved_by: str = ""

    @property
    def score(self) -> tuple[int, int] | None:
        if self.status is FixtureStatus.PLAYED and self.home_goals is not None and self.away_goals is not None:
            return (self.home_goals, self.away_goals)
        return None


@dataclass
class Competition:
    id: str
    name: str
    comp_type: CompetitionType
    nation: str
    tier: int
    club_ids: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    trophy_name: str = ""

    @property
    def kind(self) -> str:
        return str(self.comp_type)


@dataclass
class Season:
    id: str
    name: str
    start_year: int
    end_year: int
    total_weeks: int
    competition_ids: list[str] = field(default_factory=list)
    current_week: int = 0
    finished: bool = False

    def __post_init__(self) -> None:
        self.current_week = max(0, min(int(self.current_week), self.total_weeks))


@dataclass
class Transfer:
    id: str
    player_id: str
    from_club_id: str | None
    to_club_id: str | None
    transfer_type: TransferType
    fee: int
    weekly_wage: int
    contract_years: int
    status: TransferStatus = TransferStatus.PROPOSED
    season: str = ""
    week: int = 0
    notes: str = ""


@dataclass
class NewsArticle:
    id: str
    season: str
    week: int
    category: NewsCategory
    headline: str
    body: str
    clubs_involved: list[str] = field(default_factory=list)
    players_involved: list[str] = field(default_factory=list)


@dataclass
class SquadSelection:
    club_id: str
    formation: str = "4-3-3"
    starter_ids: list[str] = field(default_factory=list)
    substitute_ids: list[str] = field(default_factory=list)
    captain_id: str | None = None
    set_piece_taker_id: str | None = None


@dataclass
class IncomingOffer:
    """A purchase bid an AI club makes for one of the user's players."""

    id: str
    player_id: str
    buyer_club_id: str
    fee: int
    weekly_wage: int
    contract_years: int
    season: str = ""
    week: int = 0
    status: str = "pending"  # pending | accepted | refused | withdrawn


@dataclass
class CareerState:
    version: int
    career_id: str
    manager_name: str
    difficulty: Difficulty
    seed: int
    user_club_id: str
    current_season: str
    current_week: int
    manager: Manager
    clubs: dict[str, Club] = field(default_factory=dict)
    players: dict[str, Player] = field(default_factory=dict)
    competitions: dict[str, Competition] = field(default_factory=dict)
    seasons: dict[str, Season] = field(default_factory=dict)
    fixtures: list[Fixture] = field(default_factory=list)
    news: list[NewsArticle] = field(default_factory=list)
    transfers: list[Transfer] = field(default_factory=list)
    incoming_offers: list[IncomingOffer] = field(default_factory=list)
    selections: dict[str, SquadSelection] = field(default_factory=dict)
    matchday_history: list[str] = field(default_factory=list)
    created_at: str = ""
    title: str = ""

    def club(self, club_id: str) -> Club:
        return self.clubs[club_id]

    def player(self, player_id: str) -> Player:
        return self.players[player_id]

    def user_club(self) -> Club:
        return self.clubs[self.user_club_id]