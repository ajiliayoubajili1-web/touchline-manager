"""Tests for the editorial news desk (Phase 7)."""

import unittest

from manager.core.enums import NewsCategory
from manager.core.models import CareerState
from manager.systems.news import NEWS_CAP


def make_career(seed: int = 2026) -> CareerState:
    from manager.api.careers import new_career

    return new_career(
        first_name="Remy", last_name="Duran", nationality="Valland",
        club_id="clb_northbay", difficulty="manager",
        objective_key="steady", seed=seed, names_file=None,
    )


class NewsSystemTest(unittest.TestCase):
    def test_roundup_written_after_a_week(self):
        from manager.systems.match import simulate_week

        state = make_career()
        simulate_week(state)
        roundups = [
            n for n in state.news
            if n.category is NewsCategory.MATCH_RESULT and "round-up" in n.headline.lower()
        ]
        self.assertTrue(roundups, "a week round-up article should be written")
        self.assertEqual(roundups[-1].week, 1)
        self.assertTrue(roundups[-1].headline and roundups[-1].body)

    def test_news_is_deterministic_for_same_seed(self):
        from manager.systems.match import simulate_to_week

        a = make_career()
        b = make_career()
        simulate_to_week(a, 3)
        simulate_to_week(b, 3)
        id_a = [n.id for n in a.news if "_desk_" in n.id]
        id_b = [n.id for n in b.news if "_desk_" in n.id]
        self.assertEqual(id_a, id_b)
        body_a = [n.body for n in a.news if "_desk_" in n.id]
        body_b = [n.body for n in b.news if "_desk_" in n.id]
        self.assertEqual(body_a, body_b)

    def test_scoring_race_articles_appear_over_a_season(self):
        from manager.systems.match import simulate_season

        state = make_career()
        simulate_season(state)
        headlines = "\n".join(n.headline for n in state.news)
        self.assertIn("scoring charts", headlines)
        self.assertGreaterEqual(len(state.news), 34, "one round-up per league week at least")

    def test_season_awards_are_given(self):
        from manager.systems.match import simulate_season

        state = make_career()
        simulate_season(state)
        headlines = "\n".join(n.headline for n in state.news)
        self.assertIn("Golden Boot", headlines)
        self.assertIn("Player of the season", headlines)

    def test_news_feed_stays_bounded(self):
        from manager.systems.match import simulate_season

        state = make_career()
        simulate_season(state)
        self.assertLessEqual(len(state.news), NEWS_CAP)

    def test_news_survives_save_load(self):
        from manager.core.serialization import dump, load
        from manager.systems.match import simulate_to_week

        state = make_career()
        simulate_to_week(state, 4)
        data = dump(state)
        restored = load(CareerState, data)
        self.assertEqual(
            [(n.id, n.headline, n.category) for n in state.news],
            [(n.id, n.headline, n.category) for n in restored.news],
        )


class NewsApiTest(unittest.TestCase):
    def make_service(self):
        from manager.api.service import GameService
        from manager.systems.match import simulate_to_week

        service = GameService()
        service.create_career({
            "first_name": "Remy", "last_name": "Duran",
            "nationality": "Valland", "club_id": "clb_northbay",
            "difficulty": "manager", "objective": "steady", "seed": 2026,
        })
        simulate_to_week(service.state, 5)
        return service

    def test_news_query_returns_articles_newest_first(self):
        service = self.make_service()
        view = service.query("news", {})
        self.assertEqual(view["role"], "news")
        self.assertTrue(view["articles"])
        self.assertIn("categories", view)
        self.assertEqual(view["total"], len(service.state.news))
        weeks = [a["week"] for a in view["articles"]]
        self.assertEqual(weeks, sorted(weeks, reverse=True))

    def test_news_query_filters_by_category(self):
        service = self.make_service()
        view = service.query("news", {"category": "match_result"})
        self.assertTrue(view["articles"])
        self.assertTrue(all(a["category"] == "match_result" for a in view["articles"]))
        self.assertEqual(view["shown"], sum(1 for n in service.state.news
                                            if str(n.category) == "match_result"))

    def test_news_articles_include_rich_fields(self):
        service = self.make_service()
        view = service.query("news", {})
        sample = view["articles"][0]
        self.assertTrue(sample["headline"])
        self.assertTrue(sample["season"])
        self.assertIsInstance(sample["week"], int)
        self.assertIn("clubs", sample)
        self.assertIn("players", sample)


if __name__ == "__main__":
    unittest.main()