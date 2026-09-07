"""Enumerations used throughout the game.

All enums are :class:`enum.StrEnum` so they serialize to their string value
automatically and compare cleanly with plain strings.
"""

from __future__ import annotations

from enum import StrEnum


class Difficulty(StrEnum):
    RECRUIT = "recruit"
    COACH = "coach"
    MANAGER = "manager"
    LEGEND = "legend"


class Position(StrEnum):
    GK = "GK"
    LB = "LB"
    CB = "CB"
    RB = "RB"
    WB = "WB"
    DM = "DM"
    CM = "CM"
    AM = "AM"
    LM = "LM"
    RM = "RM"
    LW = "LW"
    RW = "RW"
    CF = "CF"
    ST = "ST"


class PersonalityTrait(StrEnum):
    PROFESSIONAL = "professional"
    AMBITIOUS = "ambitious"
    LOYAL = "loyal"
    DEMANDING = "demanding"
    CALM = "calm"
    COMPETITIVE = "competitive"
    CONFIDENT = "confident"
    EASYGOING = "easygoing"
    PERFECTIONIST = "perfectionist"
    DETERMINED = "determined"
    ECCENTRIC = "eccentric"


class FixtureStatus(StrEnum):
    SCHEDULED = "scheduled"
    PLAYED = "played"
    POSTPONED = "postponed"


class TransferType(StrEnum):
    PERMANENT = "permanent"
    LOAN = "loan"
    FREE = "free"


class TransferStatus(StrEnum):
    PROPOSED = "proposed"
    NEGOTIATING = "negotiating"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    COMPLETED = "completed"


class CompetitionType(StrEnum):
    LEAGUE = "league"
    CUP = "cup"


class MatchEventType(StrEnum):
    GOAL = "goal"
    YELLOW_CARD = "yellow_card"
    RED_CARD = "red_card"
    SUBSTITUTION = "substitution"
    INJURY = "injury"


class NewsCategory(StrEnum):
    TRANSFER_RUMOR = "transfer_rumor"
    TRANSFER_DONE = "transfer_done"
    MANAGER_CHANGE = "manager_change"
    INJURY = "injury"
    CONTRACT = "contract"
    YOUNG_STAR = "young_star"
    FINANCE = "finance"
    STREAK = "streak"
    MATCH_RESULT = "match_result"
    BOARD = "board"
    GENERAL = "general"


class PlayingStyle(StrEnum):
    BALANCED = "balanced"
    CONTROLLED_POSSESSION = "controlled_possession"
    FAST_COUNTER = "fast_counter"
    RELENTLESS_PRESS = "relentless_press"
    DIRECT = "direct"


class PressingIntensity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PassingStyle(StrEnum):
    SHORT = "short"
    MIXED = "mixed"
    DIRECT = "direct"


class Tempo(StrEnum):
    SLOW = "slow"
    NORMAL = "normal"
    FAST = "fast"


class DefensiveLine(StrEnum):
    DEEP = "deep"
    NORMAL = "normal"
    HIGH = "high"


class DefensiveApproach(StrEnum):
    CAUTIOUS = "cautious"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class AttackingApproach(StrEnum):
    METHODICAL = "methodical"
    BALANCED = "balanced"
    DARING = "daring"


class Mentality(StrEnum):
    ULTRA_DEFENSIVE = "ultra_defensive"
    DEFENSIVE = "defensive"
    BALANCED = "balanced"
    ATTACKING = "attacking"
    ULTRA_ATTACKING = "ultra_attacking"


class TrainingFocus(StrEnum):
    GENERAL = "general"
    ATTACKING = "attacking"
    DEFENDING = "defending"
    TECHNICAL = "technical"
    PHYSICAL = "physical"
    GOALKEEPING = "goalkeeping"


class TrainingIntensity(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class TacticalDuty(StrEnum):
    DEFEND = "defend"
    SUPPORT = "support"
    ATTACK = "attack"