import unittest
from gate_executor import ORDER, eliminate_player, execute_gate_matrix

class GateExecutorTests(unittest.TestCase):
    def test_complete_order(self):
        self.assertEqual(len(ORDER), 20)
        self.assertEqual(ORDER[0], "G0")
        self.assertEqual(ORDER[11], "G10.5")
        self.assertEqual(ORDER[-1], "G18")

    def test_every_skater_processed(self):
        player = {"playerId": 1, "player": "Skater", "gateTrace": [
            {"gate": g, "status": "PASS", "evidence": ["source"]} for g in ORDER
        ]}
        report = {"games": [{"game": {"gameId": 9}, "players": [player, dict(player, playerId=2)]}]}
        matrix = execute_gate_matrix(report)
        self.assertEqual(matrix["playersEvaluated"], 2)
        self.assertEqual(matrix["playersFullySurvived"], 2)

    def test_missing_evidence_never_passes(self):
        result = eliminate_player({"playerId": 1, "gateTrace": [{"gate": "G0", "status": "PASS"}]})
        self.assertFalse(result["survived"])
        self.assertFalse(result["complete"])

    def test_elimination_stops_later_gates(self):
        trace = [{"gate": g, "status": "PASS"} for g in ORDER]
        trace[4]["status"] = "ELIMINATED"
        result = eliminate_player({"playerId": 1, "gateTrace": trace})
        self.assertTrue(result["eliminated"])
        self.assertEqual(result["decisions"][5]["decision"], "SKIPPED_AFTER_ELIMINATION")

    def test_g13_qualitative_nonblocking(self):
        trace = [{"gate": g, "status": "PASS"} for g in ORDER]
        trace[ORDER.index("G13")]["status"] = "QUALITATIVE REVIEW — NONBLOCKING"
        self.assertTrue(eliminate_player({"playerId": 1, "gateTrace": trace})["survived"])

if __name__ == "__main__":
    unittest.main()
