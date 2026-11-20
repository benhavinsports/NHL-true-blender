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


def test_g9_fetches_league_peer_games_but_keeps_recent_player_logs_target_scoped(tmp_path,monkeypatch):
    import asyncio
    from nhl_true_blender_engine import historical_shots as hs
    from nhl_true_blender_engine.secondary_sources import TEAM_SLUGS
    from nhl_true_blender_engine.storage import open_db

    teams=sorted(TEAM_SLUGS)
    team_ids={team:1000+i for i,team in enumerate(teams)}
    schedules=[]
    game_index={}
    class FakeClient:
        def __init__(self):
            self.goal_mode=False
        async def get(self,path):
            team=path.split("/")[-2]
            schedules.append(team)
            idx=teams.index(team)
            games=[]
            for n in range(8):
                gid=f"{team}-{n}"
                away_id=50000+idx*10+n
                games.append({
                    "id":gid,"gameDate":f"2026-10-{n+1:02d}","gameState":"OFF",
                    "homeTeam":{"id":team_ids[team],"abbrev":team},
                    "awayTeam":{"id":away_id,"abbrev":f"X{idx}-{n}"}})
                game_index[gid]={"team":team,"awayId":away_id}
            return {"data":{"games":games}}
        async def play_by_play(self,gid):
            info=game_index[gid]
            plays=[{
                "eventId":1,"typeDescKey":"shot-on-goal",
                "periodDescriptor":{"periodType":"REG","number":1},
                "timeInPeriod":"04:00",
                "details":{"shootingPlayerId":999,"eventOwnerTeamId":info["awayId"],
                           "goalieInNetId":888,"xCoord":42,"yCoord":23,
                           "shotType":"wrist"}}]
            if self.goal_mode:
                plays.append({
                    "eventId":2,"typeDescKey":"goal",
                    "periodDescriptor":{"periodType":"REG","number":1},
                    "timeInPeriod":"05:00",
                    "details":{"scoringPlayerId":999,"eventOwnerTeamId":info["awayId"],
                               "goalieInNetId":888,"xCoord":42,"yCoord":23,
                               "shotType":"wrist"}})
            return {"url":f"https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play",
                    "data":{"plays":plays}}
    captured={}
    async def fake_boxes(client,con,snapshot,date,stage,game_dates,events):
        captured["box_game_count"]=len(game_dates)
        captured["box_event_count"]=len(events)
        return {"attemptedGames":len(game_dates)}
    async def fake_shifts(game_dates,events,meta):
        captured["shift_game_count"]=len(game_dates)
        return {"byDefendingTeamId":{},"chartedGames":0,
                "matchedDefensiveShotEvents":0}
    def fake_coverage(con,snapshot,date,stage,events,meta,shifts):
        captured["coverage_game_count"]=len(meta)
        captured["coverage_event_count"]=len(events)
        return {"coverageAttackSides":2}
    monkeypatch.setattr(hs,"collect_sampled_boxes",fake_boxes)
    monkeypatch.setattr(hs,"collect_shift_coverage",fake_shifts)
    monkeypatch.setattr(hs,"make_coverage",fake_coverage)

    snapshot={"games":[{
        "id":"TODAY","date":"2026-11-16","away":"MTL","home":"NYR",
        "rosters":{
            "MTL":{"data":{"players":[{"id":999,"name":"Target"}]}},
            "NYR":{"data":{"players":[{"id":998,"name":"Opponent"}]}}}}]}
    con=open_db(str(tmp_path/"league-peer.sqlite"))
    client=FakeClient()
    result=asyncio.run(hs.collect_history(
        client,con,snapshot,"2026-11-16","PROJECTED"))
    # The provider later corrects the same historical sample by adding
    # credited goals. A second run must append new immutable receipts rather
    # than crash on the fixed date/stage/player evidence key.
    client.goal_mode=True
    revised=asyncio.run(hs.collect_history(
        client,con,snapshot,"2026-11-16","PROJECTED"))
    assert revised["historicalGames"]==16
    # The official boxscore collector owns pressure and goal-credit receipts.
    # The PBP origin collector must not overwrite them with scalar aggregate
    # attempts or re-attach goals from games the player appeared against.
    assert con.execute("SELECT COUNT(*) FROM evidence WHERE kind='PLAYER_PRESSURE'").fetchone()[0]==0
    assert con.execute("SELECT COUNT(*) FROM evidence WHERE kind='PLAYER_GOAL_EVENTS'").fetchone()[0]==0
    assert set(schedules)==set(teams)
    assert result["coveragePeerTeams"]==len(teams)==32
    assert result["coveragePeerGames"]==256
    assert result["coveragePeerEvents"]==256
    assert result["historicalGames"]==16
    assert result["shotEvents"]==16
    assert captured["coverage_game_count"]==256
    assert captured["coverage_event_count"]==256
    assert captured["box_game_count"]==16
    assert captured["shift_game_count"]==16
    assert result["G9PeerSampleIsLeagueWide"] is True
    assert result["candidateRecentLogsExcludeNonTargetPeerGames"] is True
    con.close()
