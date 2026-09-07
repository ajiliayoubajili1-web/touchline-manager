"""Favourite-coach tactical identities.

Each entry maps a legendary manager to the tactical profile the user's club
should adopt as its default AI game-plan. Choosing a favourite coach at career
creation sets the user club's default tactics (mentality, pressing, passing,
tempo, defensive line and approaches) so auto-simulated matches and the opening
game plan reflect that school of football.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from manager.core.enums import (
    AttackingApproach,
    DefensiveApproach,
    DefensiveLine,
    Mentality,
    PassingStyle,
    PlayingStyle,
    PressingIntensity,
    Tempo,
)
from manager.core.models import Tactics


@dataclass(frozen=True)
class CoachProfile:
    key: str
    name: str
    tagline: str
    tactics: Tactics


COACH_PROFILES: dict[str, CoachProfile] = {
    "pep_guardiola": CoachProfile(
        key="pep_guardiola",
        name="Pep Guardiola",
        tagline="Tiki-Taka; relentless control, short passing, high line and a high press.",
        tactics=Tactics(
            formation="4-3-3",
            mentality=Mentality.ATTACKING,
            playing_style=PlayingStyle.CONTROLLED_POSSESSION,
            pressing=PressingIntensity.HIGH,
            passing=PassingStyle.SHORT,
            tempo=Tempo.NORMAL,
            defensive_line=DefensiveLine.HIGH,
            defensive_approach=DefensiveApproach.AGGRESSIVE,
            attacking_approach=AttackingApproach.METHODICAL,
        ),
    ),
    "jose_mourinho": CoachProfile(
        key="jose_mourinho",
        name="José Mourinho",
        tagline="Defensive counter-attacking; deep block, disciplined shape and ruthless breaks.",
        tactics=Tactics(
            formation="4-2-3-1",
            mentality=Mentality.DEFENSIVE,
            playing_style=PlayingStyle.FAST_COUNTER,
            pressing=PressingIntensity.LOW,
            passing=PassingStyle.DIRECT,
            tempo=Tempo.FAST,
            defensive_line=DefensiveLine.DEEP,
            defensive_approach=DefensiveApproach.CAUTIOUS,
            attacking_approach=AttackingApproach.DARING,
        ),
    ),
    "sir_alex_ferguson": CoachProfile(
        key="sir_alex_ferguson",
        name="Sir Alex Ferguson",
        tagline="Attacking wing play; fearless and direct, stretching teams down the flanks.",
        tactics=Tactics(
            formation="4-4-2",
            mentality=Mentality.ATTACKING,
            playing_style=PlayingStyle.DIRECT,
            pressing=PressingIntensity.MEDIUM,
            passing=PassingStyle.DIRECT,
            tempo=Tempo.FAST,
            defensive_line=DefensiveLine.NORMAL,
            defensive_approach=DefensiveApproach.BALANCED,
            attacking_approach=AttackingApproach.DARING,
        ),
    ),
    "carlo_ancelotti": CoachProfile(
        key="carlo_ancelotti",
        name="Carlo Ancelotti",
        tagline="Flexible possession & counter-attacking; adapts to the match and trusts his stars.",
        tactics=Tactics(
            formation="4-3-3",
            mentality=Mentality.BALANCED,
            playing_style=PlayingStyle.CONTROLLED_POSSESSION,
            pressing=PressingIntensity.MEDIUM,
            passing=PassingStyle.MIXED,
            tempo=Tempo.NORMAL,
            defensive_line=DefensiveLine.NORMAL,
            defensive_approach=DefensiveApproach.BALANCED,
            attacking_approach=AttackingApproach.BALANCED,
        ),
    ),
    "zinedine_zidane": CoachProfile(
        key="zinedine_zidane",
        name="Zinedine Zidane",
        tagline="Balanced possession & fast transitions; calm on the ball, quick to strike.",
        tactics=Tactics(
            formation="4-3-3",
            mentality=Mentality.BALANCED,
            playing_style=PlayingStyle.BALANCED,
            pressing=PressingIntensity.MEDIUM,
            passing=PassingStyle.SHORT,
            tempo=Tempo.FAST,
            defensive_line=DefensiveLine.NORMAL,
            defensive_approach=DefensiveApproach.BALANCED,
            attacking_approach=AttackingApproach.DARING,
        ),
    ),
}

DEFAULT_COACH_KEY = "pep_guardiola"


def coach_by_key(key: str) -> CoachProfile | None:
    return COACH_PROFILES.get(key)


def coach_tactics(key: str) -> Tactics | None:
    profile = coach_by_key(key)
    return replace(profile.tactics) if profile else None


def roster() -> list[dict]:
    return [
        {
            "key": profile.key,
            "name": profile.name,
            "tagline": profile.tagline,
            "mentality": str(profile.tactics.mentality.value),
            "style": str(profile.tactics.playing_style.value),
        }
        for profile in COACH_PROFILES.values()
    ]
