import unittest
from nhl_true_blender_engine.goalie_zones import validate_goal_zone_evidence

class GoalieZonesTests(unittest.TestCase):
    def test_goal_mouth_source_is_not_automatically_weakness(self):
        evidence = {"catchingHand": "L", "zonePerspective": "shooter",
                    "sourceType": "GOAL_MOUTH_IMPACT",
                    "events": [{"gameId": "123", "eventId": "77", "goalZone": "upper left",
                                "result": "goal", "sourceUrl": "https://example.org/verified-event"}]}
        result = validate_goal_zone_evidence(evidence)
        self.assertEqual(result["zoneCounts"]["upper left"]["goals"], 1)
        self.assertFalse(result["anatomicalClaimCertified"])

    def test_rink_coordinates_cannot_be_anatomical(self):
        with self.assertRaises(ValueError):
            validate_goal_zone_evidence({"catchingHand": "L", "zonePerspective": "shooter",
                "sourceType": "RINK_COORDINATES", "events": []})

    def test_missing_catching_hand_rejected(self):
        with self.assertRaises(ValueError):
            validate_goal_zone_evidence({"zonePerspective": "shooter",
                "sourceType": "GOAL_MOUTH_IMPACT", "events": []})

if __name__ == "__main__":
    unittest.main()
