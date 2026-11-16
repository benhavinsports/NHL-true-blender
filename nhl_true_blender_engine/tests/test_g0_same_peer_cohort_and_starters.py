"""True G0 must compare the same PBP peer sample, not mix source percentiles.

SYNTHETIC official-source-shaped inputs only; no real-game scorer assertion.
"""
from nhl_true_blender_engine.engine import (
    compare_g0_shared_official_pbp,compare_g0_consensus_across_starters,
    g0_full_slate
)
from nhl_true_blender_engine.enrichment import attach,ingest
from nhl_true_blender_engine.storage import open_db

SRC="https://api-web.nhle.com/v1/gamecenter/2026020011/play-by-play"
DATE="2026-11-16"

def goalie(pid,weak,edge_percentile,source_class):
    key=("leagueSavePctgPercentile" if source_class=="DERIVED_RINK_ORIGIN_NOT_ANATOMICAL"
         else "samplePeerSavePctgPercentile")
    return {
       "goalieId":pid,"status":"EXPECTED","profileReviewed":True,
       "sourceClass":source_class,"goalieProfileSourceUrl":SRC,
       "sample":{"allZoneObservations":85},
       "counterevidence":{"dated":True},
       "weakZones":{weak:{"shotsAgainst":45,"goalsAgainst":6,
                         key:edge_percentile}},
       "sourceUrl":SRC
    }

def cohort(pid,zone,pct,population="historical-source-cohort-1"):
    return {"sourceUrl":SRC,"observedAt":"2026-11-16T11:00:00Z",
       "data":{"team":"AAA","goalieId":pid,
          "sourceClass":"INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY",
          "samplePeerPopulationId":population,
          "peerSampleNeverLeagueEDGEPercentile":True,
          "weakZones":{zone:{
             "samplePeerSavePctgPercentile":pct,
             "shotsAgainst":45,"goalsAgainst":6,
             "peerComparedSameOrigin":True,"peerGoaliesSampled":8
          }}
       }}

def direction(attacker,defender,source,peer=None):
    target=source.copy()
    if peer:target["sameCohortPbp"]=peer
    return {"attacker":attacker,"defender":defender,
            "gameId":"9009","goalieProfileEvidenced":True,
            "targetGoalies":[target]}

def test_cross_source_goalies_get_a_common_official_historical_pool():
    a=direction("AAA","BBB",
       goalie("1","Low Slot",.3,"INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY"),
       cohort("1","Low Slot",.1))
    b=direction("BBB","AAA",
       goalie("2","High Slot",.2,"DERIVED_RINK_ORIGIN_NOT_ANATOMICAL"),
       cohort("2","High Slot",.3))
    result=compare_g0_shared_official_pbp(a,b)
    assert result is not None
    assert result["attacker"]=="AAA"
    assert result["g0SelectionMethod"]=="SAME_HISTORICAL_OFFICIAL_PBP_GOALIE_PEER_POOL"
    assert result["g0DecisionProof"]["samePeerPopulationId"]=="historical-source-cohort-1"
    assert result["g0DecisionProof"]["notGloveBlockerFiveHole"] is True
    assert compare_g0_consensus_across_starters(a,b)["attacker"]=="AAA"

def test_mismatched_or_insufficient_source_cohorts_never_create_a_g0_winner():
    a=direction("AAA","BBB",goalie("1","Low Slot",.1,"DERIVED_RINK_ORIGIN_NOT_ANATOMICAL"),
                cohort("1","Low Slot",.1))
    b=direction("BBB","AAA",goalie("2","High Slot",.3,"INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY"),
                cohort("2","High Slot",.3,"different-population"))
    assert compare_g0_shared_official_pbp(a,b) is None
    assert compare_g0_consensus_across_starters(a,b) is None
    b["targetGoalies"][0]["sameCohortPbp"]["data"]["samplePeerPopulationId"]="historical-source-cohort-1"
    b["targetGoalies"][0]["sameCohortPbp"]["data"]["weakZones"]["High Slot"]["peerGoaliesSampled"]=2
    assert compare_g0_shared_official_pbp(a,b) is None

def test_multiple_projected_goalies_require_unanimous_source_comparison():
    a=direction("AAA","BBB",
        goalie("1","Low Slot",.10,"DERIVED_RINK_ORIGIN_NOT_ANATOMICAL"))
    a["targetGoalies"].append(goalie("1b","L Circle",.15,"DERIVED_RINK_ORIGIN_NOT_ANATOMICAL"))
    b=direction("BBB","AAA",
        goalie("2","High Slot",.32,"DERIVED_RINK_ORIGIN_NOT_ANATOMICAL"))
    choice=compare_g0_consensus_across_starters(a,b)
    assert choice is not None
    assert choice["attacker"]=="AAA"
    assert len(choice["targetGoalies"])==2
    assert choice["g0DecisionProof"]["allProjectedGoalieCombinationsIndependentlyChecked"]==2
    assert choice["g0DecisionProof"]["projectedBranchesNeverSilentlyConfirmed"] is True
    a["targetGoalies"][1]["weakZones"]["L Circle"]["leagueSavePctgPercentile"]=.34
    b["targetGoalies"][0]["weakZones"]["High Slot"]["leagueSavePctgPercentile"]=.20
    assert compare_g0_consensus_across_starters(a,b) is None

def test_attaching_peer_context_does_not_replace_original_starter_or_edge(tmp_path):
    db=open_db(str(tmp_path/"attach.sqlite"))
    game={"id":"9009","away":"AAA","home":"BBB",
          "goalies":{"AAA":[],"BBB":[{
             "sourceUrl":SRC,"observedAt":"2026-11-16T11:00:00Z",
             "data":{"goalieId":"1","team":"BBB","status":"EXPECTED",
                     "weakZones":{"Low Slot":{}}}
          }]},"rosters":{},"coverage":{}}
    data=cohort("1","Low Slot",.1)["data"]
    data["team"]="BBB"
    ingest(db,{"evidence_id":"peer-context-receipt","slate_date":DATE,
        "stage":"PROJECTED","game_id":"9009",
        "kind":"GOALIE_PBP_PEER_CONTEXT",
        "source_url":SRC,"observed_at":"2026-11-16T11:00:00Z",
        "payload":data})
    attach(db,{"games":[game]},DATE,"PROJECTED")
    assert game["goalies"]["BBB"][0]["data"]["status"]=="EXPECTED"
    assert game["goalies"]["BBB"][0]["data"]["weakZones"]=={"Low Slot":{}}
    assert game["goaliePeerContexts"]["1"]["data"]["samplePeerPopulationId"]=="historical-source-cohort-1"
    scan,notes=g0_full_slate([game],"PROJECTED")
    assert scan[0]["targetGoalies"][0]["sameCohortPbp"]["data"]["goalieId"]=="1"
    db.close()
