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
                {"gameId": i, "playerId": i + 1, "gateTrace": [{"gate": g, "status": "PASS"} for g in ([f"G{j}" for j in range(19)] + ["G10.5"])]}
                for i in ids
            ]}
        }

    def test_missing_or_unpassed_gate_cannot_publish(self):
        with tempfile.TemporaryDirectory() as d:
            report = self.report()
            report["coreOutput"]["core"][0]["gateTrace"] = [
                x for x in report["coreOutput"]["core"][0]["gateTrace"]
                if x["gate"] != "G10.5"
            ]
            with self.assertRaisesRegex(ValueError, "missing gate"):
                publish_verified_core(report, d)
            self.assertEqual(list(Path(d).glob("authoritative*")), [])
        with tempfile.TemporaryDirectory() as d:
            report = self.report()
            report["coreOutput"]["core"][0]["gateTrace"][0]["status"] = "UNRESOLVED"
            with self.assertRaisesRegex(ValueError, "unpassed gate"):
                publish_verified_core(report, d)
            self.assertEqual(list(Path(d).glob("authoritative*")), [])

    def test_uncertified_does_not_publish(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(publish_verified_core(self.report(certified=False), d)["published"])
            self.assertEqual(list(Path(d).glob("authoritative*")), [])

    def test_pass_shaped_legacy_report_cannot_create_an_independent_card(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.report()
            self.assertFalse(publish_verified_core(r, d)["published"])
            self.assertFalse(publish_verified_core(r, d)["published"])
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_conflicting_card_cannot_replace(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d, "authoritative_core_2026-11-15.json")
            original=json.dumps({"core":self.report()["coreOutput"]["core"]})
            path.write_text(original)
            rejected = publish_verified_core(self.report((101, 202, 404)), d)
            self.assertFalse(rejected["published"])
            self.assertEqual(path.read_text(),original)
            card = json.loads(path.read_text())
            self.assertEqual([p["gameId"] for p in card["core"]], [101, 202, 303])

if __name__ == "__main__":
    unittest.main()

