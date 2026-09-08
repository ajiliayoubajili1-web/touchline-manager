"""Club definitions for the Valland Super League.

A closed super league of eighteen clubs: ten footballing giants, seven solid
mid-tier clubs and one very, very poor outfit. All player names are fictional
(no real players appear); club names and cities echo the real world for
flavour only. Definitions are static metadata; squads, finances and
personalities are generated at world build time.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClubDef:
    slug: str
    name: str
    city: str
    stadium: str
    capacity: int
    primary: str
    secondary: str
    reputation: int
    founded: int


CLUB_DEFS: list[ClubDef] = [
    # --- ten super clubs ------------------------------------------------
    ClubDef("northbay", "Real Madrid", "Madrid", "Santiago Bernabeu", 81044, "#f0f0f0", "#febe10", 98, 1902),
    ClubDef("barca", "Barcelona", "Barcelona", "Camp Nou", 99354, "#a50044", "#004d98", 97, 1899),
    ClubDef("city", "Manchester City", "Manchester", "Etihad Stadium", 53400, "#6cabdd", "#1c2c5b", 96, 1880),
    ClubDef("bayern", "Bayern Munchen", "Munich", "Allianz Arena", 75024, "#dc052d", "#0066b2", 96, 1900),
    ClubDef("liverpool", "Liverpool", "Liverpool", "Anfield", 61276, "#c8102e", "#00b2a9", 95, 1892),
    ClubDef("milan_ac", "AC Milan", "Milan", "San Siro", 75817, "#fb090b", "#000000", 94, 1899),
    ClubDef("paris", "Paris Saint-Germain", "Paris", "Parc des Princes", 47929, "#004170", "#da291c", 94, 1970),
    ClubDef("dortmund", "Borussia Dortmund", "Dortmund", "Signal Iduna Park", 81365, "#fde100", "#000000", 93, 1909),
    ClubDef("arsenal", "Arsenal", "London", "Emirates Stadium", 60704, "#ef0107", "#ffffff", 92, 1886),
    ClubDef("inter", "Inter", "Milan", "San Siro", 75817, "#0068a8", "#000000", 92, 1908),
    # --- seven medium clubs ---------------------------------------------
    ClubDef("roma", "Roma", "Rome", "Stadio Olimpico", 70634, "#8e1f2f", "#f0bc42", 82, 1927),
    ClubDef("leverkusen", "Bayer Leverkusen", "Leverkusen", "BayArena", 30210, "#e32221", "#000000", 81, 1904),
    ClubDef("westham", "West Ham United", "London", "London Stadium", 62500, "#7a263a", "#1bb1e7", 80, 1895),
    ClubDef("monaco", "Monaco", "Monaco", "Stade Louis II", 18523, "#e63312", "#ffffff", 78, 1924),
    ClubDef("bilbao", "Athletic Bilbao", "Bilbao", "San Mames", 53289, "#ee2523", "#ffffff", 77, 1898),
    ClubDef("leicester", "Leicester City", "Leicester", "King Power Stadium", 32262, "#003090", "#fdb515", 76, 1884),
    ClubDef("como", "Como", "Como", "Stadio Sinigaglia", 13602, "#2563eb", "#ffffff", 70, 1907),
    # --- one very, very bad club ----------------------------------------
    ClubDef("sfax", "Club Sportif Sfaxien", "Sfax", "Stade Taieb Mhiri", 11000, "#000000", "#ffffff", 42, 1928),
]

REPUTATION_ORDER = sorted((d.slug for d in CLUB_DEFS), key=lambda s: next(d.reputation for d in CLUB_DEFS if d.slug == s), reverse=True)

TIER_1_SLUGS = ["northbay", "barca", "city", "bayern", "liverpool", "milan_ac", "paris", "dortmund", "arsenal", "inter"]
TIER_2_SLUGS = ["roma", "leverkusen", "westham", "monaco", "bilbao", "leicester", "como"]
TIER_3_SLUGS = ["sfax"]


def club_def_by_slug(slug: str) -> ClubDef:
    return next(d for d in CLUB_DEFS if d.slug == slug)