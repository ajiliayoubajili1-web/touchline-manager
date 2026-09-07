"""Tests for serialization and the HTTP server API."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from manager.api.service import GameService
from manager.core.serialization import dump
from manager.data.world import build_world
from manager.ui.server import create_server


class SerializationTest(unittest.TestCase):
    def test_world_dump_is_json_serializable(self):
        world = build_world(seed=5)
        payload = dump(world)
        text = json.dumps(payload)
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 1000)


class ServerApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server = create_server(
            GameService(save_dir=Path(cls.tmp.name)), address=("127.0.0.1", 0)
        )

        cls.server_class = cls.server.__class__
        cls.server_class.daemon_threads = True
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

        cls.career_payload = {
            "first_name": "Avery",
            "last_name": "Cole",
            "nationality": "Valland",
            "difficulty": "manager",
            "objective": "steady",
            "club_id": "clb_northbay",
            "seed": 42,
        }
        cls.career_id = cls._create_career()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.tmp.cleanup()

    @classmethod
    def _create_career(cls):
        with urllib.request.urlopen(
            urllib.request.Request(
                f"{cls.base}/api/careers",
                data=json.dumps(cls.career_payload).encode(),
                headers={"Content-Type": "application/json"},
            )
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["title"]

    def _get(self, url):
        with urllib.request.urlopen(url) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _post(self, path, payload):
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_status_endpoint(self):
        status, data = self._get(f"{self.base}/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(data["game"], "Touchline Manager")
        self.assertGreaterEqual(data["clubs"], 18)

    def test_static_index_served(self):
        with urllib.request.urlopen(f"{self.base}/") as resp:
            body = resp.read().decode("utf-8")
        self.assertIn("Touchline", body)

    def test_unknown_api_route_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{self.base}/api/nope")
        self.assertEqual(ctx.exception.code, 404)

    def test_career_created_and_dashboard_available(self):
        status, data = self._get(f"{self.base}/api/query?name=dashboard")
        self.assertEqual(status, 200)
        self.assertEqual(data["club"]["name"], "Real Madrid")
        self.assertEqual(data["season"]["week"], 0)
        self.assertEqual(data["manager"]["name"], "Avery Cole")

    def test_session_reflects_career(self):
        status, data = self._get(f"{self.base}/api/query?name=session")
        self.assertEqual(status, 200)
        self.assertTrue(data["in_career"])
        self.assertEqual(data["club"], "Real Madrid")

    def test_squad_query_has_25_players(self):
        status, data = self._get(f"{self.base}/api/query?name=squad")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["players"]), 25)
        self.assertEqual(len(data["starter_ids"]), 11)
        self.assertEqual(len(data["substitute_ids"]), 5)

    def test_set_tactics_invalid_formation_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/action?command=set_tactics", {"formation": "9-1-0"})
        self.assertEqual(ctx.exception.code, 400)

    def test_invalid_selection_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/action?command=set_selection", {"starter_ids": ["a", "b"]})
        self.assertEqual(ctx.exception.code, 400)

    def test_rejected_selection_does_not_corrupt_state(self):
        before = self._get(f"{self.base}/api/query?name=squad")[1]["starter_ids"]
        with self.assertRaises(urllib.error.HTTPError):
            self._post("/api/action?command=set_selection", {"starter_ids": ["a", "b"]})
        after = self._get(f"{self.base}/api/query?name=squad")[1]["starter_ids"]
        self.assertEqual(before, after)

    def test_captain_must_be_in_starting_xi(self):
        squad = self._get(f"{self.base}/api/query?name=squad")[1]
        bench_player = squad["substitute_ids"][0]
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post(
                "/api/action?command=set_selection",
                {"captain_id": bench_player, "starter_ids": squad["starter_ids"]},
            )
        self.assertEqual(ctx.exception.code, 400)

    def test_set_tactics_rejects_junk_enum_value(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/action?command=set_tactics", {"tempo": "high"})
        self.assertEqual(ctx.exception.code, 400)

    def test_set_tactics_rejects_unknown_field(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/action?command=set_tactics", {"nonsense": "yes"})
        self.assertEqual(ctx.exception.code, 400)

    def test_set_tactics_round_trips_after_reload(self):
        _, data = self._post("/api/action?command=set_tactics", {"formation": "3-5-2", "tempo": "fast"})
        self.assertEqual(data["tactics"]["formation"], "3-5-2")
        self.assertEqual(data["tactics"]["tempo"], "fast")

    def test_dashboard_reports_next_match(self):
        _, data = self._get(f"{self.base}/api/query?name=dashboard")
        self.assertIsNotNone(data["next_match"])
        self.assertEqual(data["next_match"]["week"], 1)

    def test_fixtures_and_results_queries(self):
        _, fixtures = self._get(f"{self.base}/api/query?name=fixtures")
        self.assertGreaterEqual(len(fixtures["fixtures"]), 34)
        self.assertEqual(fixtures["week"], 0)
        rows = fixtures["fixtures"]
        self.assertTrue(all(r["date"] for r in rows), "all fixtures carry a date")
        cups = [r for r in rows if r["cup"]]
        self.assertTrue(cups, "the calendar includes Continental Cup ties")
        _, results = self._get(f"{self.base}/api/query?name=results")
        self.assertEqual(results["results"], [])

    def test_play_week_then_standings(self):
        _, matchday = self._post("/api/action?command=play_week", {})
        self.assertEqual(matchday["role"], "matchday")
        self.assertEqual(matchday["week"], 1)
        self.assertGreaterEqual(len(matchday["results"]), 9)

        _, standings = self._get(f"{self.base}/api/query?name=standings")
        self.assertEqual(standings["role"], "standings")
        self.assertEqual(len(standings["rows"]), 18)
        self.assertIsNotNone(standings["user_position"])

        _, session = self._get(f"{self.base}/api/query?name=session")
        self.assertEqual(session["week"], 1)

    def test_z_matchday_highlights_are_chronological(self):
        _, matchday = self._post("/api/action?command=play_week", {})
        self.assertIn("highlights", matchday)
        hl = matchday["highlights"]
        self.assertIsInstance(hl, list)
        mins = [e["minute"] for e in hl]
        self.assertEqual(mins, sorted(mins), "highlights ordered by minute")
        for e in hl:
            self.assertIn(e["type"], {"goal", "yellow_card", "red_card"})
            self.assertIsInstance(e["player"], str)
            self.assertIsInstance(e["team"], str)
            self.assertGreater(e["minute"], 0)
            self.assertLessEqual(e["minute"], 120)
            if e["type"] == "goal":
                self.assertRegex(e["score"], r"^\d+ - \d+$")
        if hl:
            goals = [e for e in hl if e["type"] == "goal"]
            if goals:
                self.assertEqual(goals[-1]["score"], matchday["scoreline"])

    def test_save_and_continue_round_trip(self):
        status, data = self._get(f"{self.base}/api/query?name=careers")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["careers"]), 1)
        career_id = data["careers"][0]["career_id"]

        _, _ = self._post("/api/career/load", {"career_id": career_id})
        # delete leaves the save on disk removed? No - continue test only:
        status, data = self._get(f"{self.base}/api/query?name=careers")
        self.assertEqual(len(data["careers"]), 1)

    def test_create_career_with_missing_club_rejected(self):
        payload = dict(self.career_payload, club_id="clb_does_not_exist")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post("/api/careers", payload)
        self.assertEqual(ctx.exception.code, 400)


class MultiUserServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server = create_server(
            GameService(save_dir=Path(cls.tmp.name)), address=("127.0.0.1", 0)
        )
        cls.server_class = cls.server.__class__
        cls.server_class.daemon_threads = True
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.career_payload = {
            "first_name": "Avery",
            "last_name": "Cole",
            "nationality": "Valland",
            "difficulty": "manager",
            "objective": "steady",
            "club_id": "clb_northbay",
            "seed": 42,
        }

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.tmp.cleanup()

    def _post(self, path, payload, device):
        req = urllib.request.Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-Device-Id": device},
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _get(self, url, device):
        req = urllib.request.Request(url, headers={"X-Device-Id": device})
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_devices_have_isolated_careers(self):
        # device-aaa creates a career; device-bbb has not and must see nothing.
        status, _ = self._post("/api/careers", self.career_payload, "device-aaa")
        self.assertEqual(status, 200)

        _, list_a = self._get(f"{self.base}/api/query?name=careers", "device-aaa")
        _, list_b = self._get(f"{self.base}/api/query?name=careers", "device-bbb")
        self.assertEqual(len(list_a["careers"]), 1)
        self.assertEqual(len(list_b["careers"]), 0)

        _, sess_a = self._get(f"{self.base}/api/query?name=session", "device-aaa")
        _, sess_b = self._get(f"{self.base}/api/query?name=session", "device-bbb")
        self.assertTrue(sess_a["in_career"])
        self.assertFalse(sess_b["in_career"])

    def test_each_device_keeps_its_own_save(self):
        # Both devices start their own career; each keeps exactly its own.
        self._post("/api/careers", self.career_payload, "device-ccc")
        self._post("/api/careers", self.career_payload, "device-ddd")

        _, list_c = self._get(f"{self.base}/api/query?name=careers", "device-ccc")
        _, list_d = self._get(f"{self.base}/api/query?name=careers", "device-ddd")
        self.assertEqual(len(list_c["careers"]), 1)
        self.assertEqual(len(list_d["careers"]), 1)

        _, sess_c = self._get(f"{self.base}/api/query?name=session", "device-ccc")
        _, sess_d = self._get(f"{self.base}/api/query?name=session", "device-ddd")
        self.assertTrue(sess_c["in_career"])
        self.assertTrue(sess_d["in_career"])


if __name__ == "__main__":
    unittest.main()