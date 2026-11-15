import json
import tempfile
import unittest
from pathlib import Path
from core_publication import publish_verified_core

class PublicationTests(unittest.TestCase):
    def report(self, ids=(101, 202, 303), certified=True):
        return {
            "slateDate": "2026-11-15", "mode": "projected", "runId": "test",
            "gameCount": 3,
            "validationSummary": {"finalPlayerPathsCertified": certified},
            "coreOutput": {"status": "CORE 3", "core": [
                {"gameId": i, "playerId": i + 1, "gateTrace": [{"gate": "G18", "status": "PASS"}]}
                for i in ids
            ]}
        }

    def test_uncertified_does_not_publish(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(publish_verified_core(self.report(certified=False), d)["published"])
            self.assertEqual(list(Path(d).glob("authoritative*")), [])

    def test_first_card_and_identical_repeat(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.report()
            self.assertTrue(publish_verified_core(r, d)["published"])
            self.assertFalse(publish_verified_core(r, d)["published"])

    def test_conflicting_card_cannot_replace(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(publish_verified_core(self.report(), d)["published"])
            rejected = publish_verified_core(self.report((101, 202, 404)), d)
            self.assertFalse(rejected["published"])
            card = json.loads(Path(d, "authoritative_core_2026-11-15.json").read_text())
            self.assertEqual([p["gameId"] for p in card["core"]], [101, 202, 303])

if __name__ == "__main__":
    unittest.main()
