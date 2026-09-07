"""Tests for fixture generation and the round-robin schedule."""

import unittest

from manager.api.careers import new_career
from manager.systems.fixtures import compute_standings, generate_league_fixtures

CLUB_IDS = [f"clb_{i:02d}" for i in range(18)]


class RoundRobinTest(unittest.TestCase):
    def test_team_plays_everyone_home_and_away(self):
        fixtures = generate_league_fixtures("2026-27", "apex_division", CLUB_IDS)
        self.assertEqual(len(fixtures), 306)

        for club in CLUB_IDS:
            opponents = {}
            for fixture in fixtures:
                if fixture.home_club_id == club:
                    opponents.setdefault(fixture.away_club_id, []).append("h")
                if fixture.away_club_id == club:
                    opponents.setdefault(fixture.home_club_id, []).append("a")
            self.assertEqual(set(opponents), set(CLUB_IDS) - {club})
            for venue in opponents.values():
                self.assertEqual(sorted(venue), ["a", "h"], f"{club} unbalanced vs opponent")

    def test_each_week_has_nine_matches_and_each_club_once(self):
        fixtures = generate_league_fixtures("2026-27", "apex_division", CLUB_IDS)
        by_week = {}
        for fixture in fixtures:
            by_week.setdefault(fixture.week, []).append(fixture)
        self.assertEqual(len(by_week), 34)
        for week, group in by_week.items():
            self.assertEqual(len(group), 9)
            clubs = [f.home_club_id for f in group] + [f.away_club_id for f in group]
            self.assertEqual(len(set(clubs)), 18, f"week {week} repeats a club")

    def test_each_club_plays_once_per_week(self):
        fixtures = generate_league_fixtures("2026-27", "apex_division", CLUB_IDS)
        for week in range(1, 35):
            seen = set()
            for fixture in fixtures:
                if fixture.week != week:
                    continue
                self.assertNotIn(fixture.home_club_id, seen, f"week {week}")
                self.assertNotIn(fixture.away_club_id, seen, f"week {week}")
                seen.add(fixture.home_club_id)
                seen.add(fixture.away_club_id)

    def test_all_fixtures_scheduled_not_played(self):
        fixtures = generate_league_fixtures("2026-27", "apex_division", CLUB_IDS)
        self.assertTrue(all(f.score is None for f in fixtures))

    def test_deterministic_calendar(self):
        a = generate_league_fixtures("2026-27", "apex_division", CLUB_IDS)
        b = generate_league_fixtures("2026-27", "apex_division", CLUB_IDS)
        self.assertEqual([f.id for f in a], [f.id for f in b])


class StandingsTest(unittest.TestCase):
    def test_no_games_gives_empty_table(self):
        self.assertEqual(compute_standings([]), [])

    def test_beats_world_agrees_with_hand_score(self):
        from manager.core.enums import FixtureStatus

        fixtures = generate_league_fixtures("2026-27", "apex_division", CLUB_IDS)
        played = [f for f in fixtures if f.week <= 3]
        for fixture in played:
            fixture.status = FixtureStatus.PLAYED
            fixture.home_goals = 1
            fixture.away_goals = 0
        table = compute_standings(played)
        points_by_club = {row.club_id: row.points for row in table}

        for club in CLUB_IDS:
            home_games = sum(
                1 for f in played if f.home_club_id == club
            )
            self.assertEqual(points_by_club[club], 3 * home_games, club)


class CareerCalendarTest(unittest.TestCase):
    def test_career_has_full_apex_and_cup_calendar(self):
        state = new_career(
            first_name="A", last_name="B", nationality="Valland",
            club_id="clb_northbay", difficulty="manager",
            objective_key="steady", seed=42, names_file=None,
        )
        league = [f for f in state.fixtures if f.competition_id == "apex_division"]
        cup = [f for f in state.fixtures if f.competition_id == "continental_series"]
        self.assertEqual(len(league), 306)
        self.assertEqual(len(cup), 8)
        self.assertTrue(all(f.round == "round_of_16" for f in cup))
        mine = [f for f in league if f.home_club_id == "clb_northbay" or f.away_club_id == "clb_northbay"]
        self.assertEqual(len(mine), 34)
        self.assertTrue(all(f.week <= 34 for f in state.fixtures))
        user_cup = [f for f in cup if f.home_club_id == "clb_northbay" or f.away_club_id == "clb_northbay"]
        self.assertEqual(len(user_cup), 1)


if __name__ == "__main__":
    unittest.main()