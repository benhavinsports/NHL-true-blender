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
    def test_official_recent_pressure_not_overwritten_by_season_aggregate(self):
        import sqlite3
        from nhl_true_blender_engine.storage import open_db
        from nhl_true_blender_engine.enrichment import ingest, attach
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            con=open_db(d+'/test.sqlite')
            snapshot={'games':[{'id':'100','away':'NYR','home':'BOS',
                'rosters':{'NYR':{'data':{'players':[{'id':'1','name':'Test Skater'}]}},
                           'BOS':{'data':{'players':[]}}},'goalies':{},'coverage':{}}]}
            base={'slate_date':'2026-11-15','stage':'PROJECTED',
                  'game_id':'100','player_id':'1','kind':'PLAYER_PRESSURE',
                  'source_url':'https://example.com/source'}
            ingest(con,{**base,'evidence_id':'official','observed_at':'2026-11-15T10:00:00Z',
                'payload':{'evidenceType':'OFFICIAL_HISTORICAL_SHOT_EVENTS','recentAppearanceShots':12}})
            ingest(con,{**base,'evidence_id':'aggregate','observed_at':'2026-11-15T11:00:00Z',
                'payload':{'evidenceType':'SEASON_AGGREGATE_NOT_RECENT_APPEARANCES',
                           'historicalShotAttempts':100}})
            attach(con,snapshot,'2026-11-15','PROJECTED')
            pressure=snapshot['games'][0]['rosters']['NYR']['data']['players'][0]['pressure']['data']
            self.assertEqual(pressure['recentAppearanceShots'],12)
            self.assertEqual(pressure['seasonAggregate']['data']['historicalShotAttempts'],100)
            con.close()
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
