import json
import tempfile
import unittest
from pathlib import Path
from postgame_audit import audit_grade, GATE_IDS

class PostgameAuditTests(unittest.TestCase):
    def test_miss_keeps_every_gate_and_does_not_invent_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            date = "2026-11-15"
            trace = [{"gate": g, "status": "PASS", "evidence": ["observed"]} for g in GATE_IDS]
            card = {"core": [{"gameId": 42, "playerId": 99, "gateTrace": trace}]}
            grade = {"status": "GRADED", "result": "LOSS", "players": [
                {"gameId": 42, "playerId": 99, "goals": 0, "hit": False}]}
            (folder / f"authoritative_core_{date}.json").write_text(json.dumps(card))
            (folder / f"grade_{date}.json").write_text(json.dumps(grade))
            audit = audit_grade(date, folder)
            self.assertEqual(audit["status"], "AUDITED")
            self.assertEqual(len(audit["misses"][0]["gateAudit"]), len(GATE_IDS))
            self.assertEqual(audit["patchesApplied"], [])
            self.assertEqual(audit_grade(date, folder)["status"], "AUDITED")

    def test_no_card_never_creates_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            result = audit_grade("2026-11-15", directory)
            self.assertEqual(result["status"], "WAITING_FOR_GRADE_OR_CARD")
            self.assertFalse(list(Path(directory).glob("audit*")))

if __name__ == "__main__":
    unittest.main()
