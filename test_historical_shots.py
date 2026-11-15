import unittest
from nhl_true_blender_engine.historical_shots import extract_events, shooter_summary, goalie_summary

class HistoricalShotTests(unittest.TestCase):
    def test_source_provenance_and_goalie_identity(self):
        raw = {"url": "https://api-web.nhle.com/v1/gamecenter/123/play-by-play",
               "data": {"plays": [
                   {"eventId": 1, "typeDescKey": "shot-on-goal", "periodDescriptor": {"periodType": "REG"},
                    "details": {"shootingPlayerId": 42, "goalieInNetId": 77, "shotType": "wrist",
                                "xCoord": 65, "yCoord": 4}},
                   {"eventId": 2, "typeDescKey": "goal", "periodDescriptor": {"periodType": "REG"},
                    "details": {"scoringPlayerId": 42, "goalieInNetId": 77, "shotType": "snap"}},
                   {"eventId": 3, "typeDescKey": "goal", "periodDescriptor": {"periodType": "SO"},
                    "details": {"scoringPlayerId": 42, "goalieInNetId": 77}}
               ]}}
        events = extract_events(raw, 123, "2026-11-10")
        self.assertEqual(len(events), 2)
        self.assertEqual(shooter_summary(events, 42)["ownedGoals"], 1)
        self.assertEqual(goalie_summary(events, 77)["goalsAgainst"], 1)
        self.assertFalse(goalie_summary(events, 77)["anatomicalWeaknessVerified"])
        self.assertEqual(events[0]["sourceUrl"], raw["url"])

if __name__ == "__main__":
    unittest.main()
