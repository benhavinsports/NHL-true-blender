import unittest
from nhl_true_blender_engine.lineup_parser import parse_markdown
from nhl_true_blender_engine.sources import roster_as_evidence

class EvidenceAdaptersTest(unittest.TestCase):
    def test_official_goalie_ids_preserved(self):
        raw={"url":"https://api-web.nhle.com/v1/roster/NYR/current",
             "observedAt":"2026-11-15T12:00:00Z",
             "data":{"forwards":[],"defensemen":[],
                     "goalies":[{"id":8478048,"firstName":{"default":"Igor"},
                                 "lastName":{"default":"Shesterkin"}}]}}
        result=roster_as_evidence(raw,"NYR")
        self.assertEqual(result["data"]["goalies"],[{"id":"8478048","name":"Igor Shesterkin"}])
    def test_goalie_parser_is_not_team_confirmation(self):
        data=parse_markdown("- Igor Shesterkin (NYR), Unconfirmed")
        self.assertEqual(data["goalies"][0]["status"],"UNCONFIRMED")
    def test_scorer_pool_excludes_goalies(self):
        from nhl_true_blender_engine.engine import complete_roster
        game={"away":"NYR","home":"BOS","rosters":{"NYR":{
            "sourceUrl":"https://api-web.nhle.com/v1/roster/NYR/current",
            "observedAt":"2026-11-15T12:00:00Z",
            "data":{"players":[{"id":"1","position":"C"},{"id":"2","position":"D"}],
                    "goalies":[{"id":"3","name":"Goalie"}]}}}}
        self.assertEqual(len(complete_roster(game,"NYR")),2)

if __name__=="__main__":
    unittest.main()
