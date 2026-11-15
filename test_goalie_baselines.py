import unittest
from nhl_true_blender_engine.goalie_baselines import wilson, compare_goalie_to_baseline

def evidence(goals, saves):
    events=[]
    for i in range(goals+saves):
        events.append({"gameId":str(i//20+1),"eventId":str(i+1),
                       "goalZone":"upper left","result":"goal" if i<goals else "save",
                       "sourceUrl":"https://example.org/source"})
    return {"catchingHand":"L","zonePerspective":"shooter",
            "sourceType":"GOAL_MOUTH_IMPACT","events":events}

class GoalieBaselineTests(unittest.TestCase):
    def test_high_failure_rate_exceeds_baseline(self):
        result=compare_goalie_to_baseline(evidence(60,40),evidence(20,180))
        self.assertIn("upper left",result["weakZones"])
        self.assertTrue(result["anatomicalHandMappingRequired"])

    def test_equal_rates_not_weakness(self):
        result=compare_goalie_to_baseline(evidence(10,90),evidence(10,90))
        self.assertNotIn("upper left",result["weakZones"])

    def test_tiny_sample_not_certified(self):
        result=compare_goalie_to_baseline(evidence(2,0),evidence(2,0))
        self.assertEqual(result["zones"]["upper left"]["status"],"INSUFFICIENT_SAMPLE")

    def test_invalid_denominator(self):
        with self.assertRaises(ValueError):
            wilson(3,2)

if __name__=="__main__":
    unittest.main()
