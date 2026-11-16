"""NHL G0 goalie peer evidence must be collected before declaring it unavailable.

All inputs here are explicitly SYNTHETIC game-log/PBP fixtures. No odds,
fabricated real starters, anatomical claims, or postgame look-ahead.
"""
import asyncio
import json
import nhl_true_blender_engine.goalie_history_fallback as fb
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import game,evidence

DATE="2026-11-16"
SRC="https://api-web.nhle.com/v1/gamecenter/2026020101/play-by-play"

def goalie(pid,team,needs_fallback):
    return evidence({
        "goalieId":pid,"team":team,"status":"EXPECTED",
        "sourceClass":"DERIVED_RINK_ORIGIN_NOT_ANATOMICAL",
        "sourceReviewed":not needs_fallback,
        "observedAreas":{"Low Slot":{
            "shotsAgainst":22,"goalsAgainst":4,
            "leagueSavePctgPercentile":.32}},
        "sample":{"allZoneObservations":22},
        "weakZones":{} if needs_fallback else {
            "Low Slot":{"shotsAgainst":22,"goalsAgainst":4,
                        "leagueSavePctgPercentile":.32}},
        "counterevidence":{"observedRinkOriginOnly":True},
    },source=SRC)

def test_official_goalie_history_collects_comparable_pre_slate_peer_sample(tmp_path,monkeypatch):
    clubs=[game(1),game(2),game(3)]
    goalie_ids=[str(740+i) for i in range(5)]
    for i,g in enumerate(clubs):
        for team in (g["away"],g["home"]):
            g["goalies"][team]=[]
    # One goalie without an adequate EDGE area and four other slate goalies
    # already fully reviewed independently. The four are PEERS only and must
    # never be reclassified as missing G0 sources or changed to confirmed.
    team_sides=[(clubs[0],clubs[0]["away"]),(clubs[0],clubs[0]["home"]),
                (clubs[1],clubs[1]["away"]),(clubs[1],clubs[1]["home"]),
                (clubs[2],clubs[2]["away"])]
    for i,(match,team) in enumerate(team_sides):
        match["goalies"][team]=[goalie(goalie_ids[i],team,i==0)]
    counts={goalie_ids[i]:8-i for i in range(5)}
    by_game={str(9000+i):gid for i,gid in enumerate(goalie_ids)}
    class Client:
        def __init__(self):self.personal_logs=[];self.fetches=[]
        async def game_log(self,pid,season):
            self.personal_logs.append((pid,season))
            return {"data":{"gameLog":[{
                "gameId":int(gid),"gameDate":"2026-11-11"}
                for gid,p in by_game.items() if p==pid
            ] if season=="20262027" else []}}
        async def play_by_play(self,gid):
            self.fetches.append(str(gid))
            pid=by_game[str(gid)]
            # One goalie, 25 observed shots from the SAME actual rink-origin
            # coordinate area. NHL sample IDs are synthetic in this fixture.
            events=[{
                "gameId":str(gid),"eventId":str(i),"goalieId":pid,
                "type":"goal" if i<=counts[pid] else "shot-on-goal",
                "x":82,"y":4,
                "sourceUrl":SRC,"date":"2026-11-11",
            } for i in range(1,26)]
            return {"data":{"synthetic":events}}
    monkeypatch.setattr(fb,"extract_events",
                       lambda raw,gid,played:raw["data"]["synthetic"])
    client=Client()
    con=open_db(str(tmp_path/"ledger.sqlite"))
    result=asyncio.run(fb.collect_goalie_pbp_fallback(
        client,con,{"games":clubs},DATE,"PROJECTED"))
    assert result["goaliesNeedingPbpResearch"]==1
    assert result["independentlyIdentifiedSlateGoaliePeers"]==5
    assert result["historicalNhlGamesFetched"]==5
    assert result["goaliesWithPeerComparedOrigins"]==1
    assert result["fallbackProfiles"]==1
    assert result["anatomicalClaimCertified"] is False
    assert len(client.personal_logs)==10
    assert set(client.fetches)==set(by_game)
    row=con.execute("""SELECT payload FROM evidence
      WHERE kind='GOALIE_PROFILE'""").fetchone()
    assert row is not None
    payload=json.loads(row["payload"])
    assert payload["goalieId"]==goalie_ids[0]
    assert payload["weakZones"]["Low Slot"]["peerGoaliesSampled"]==4
    assert payload["weakZones"]["Low Slot"]["samplePeerSavePctgPercentile"]==0
    assert payload["anatomicalWeaknessCertified"] is False
    assert con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]==1
    con.close()
