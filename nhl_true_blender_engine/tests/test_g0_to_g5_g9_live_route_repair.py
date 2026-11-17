"""Regression: the original G0 source reaches skater gates; G9 uses real concessions.

Synthetic source-shaped data; no scorers, games or gate verdicts are hand-picked.
"""
import json
from nhl_true_blender_engine.engine import g0_source_coherent_scorer_goalie
from nhl_true_blender_engine.official_defense_coverage import make_coverage
from nhl_true_blender_engine.semantic_certification import audit_gate
from nhl_true_blender_engine.storage import open_db

SRC="https://api-web.nhle.com/v1/gamecenter/2025020802/play-by-play"
DATE="2026-11-17"

def g0_scene():
    starter={"sourceUrl":SRC,"observedAt":"2026-11-17T10:00:00+00:00",
      "data":{"goalieId":"8478499","team":"VGK","status":"EXPECTED",
              "weakZones":{},"strengthZones":{},"sample":{"allZoneObservations":75},
              "counterevidence":{"noEdgeWeakness":True}}}
    peer={"sourceUrl":SRC,"observedAt":"2026-11-17T10:15:00+00:00","evidenceId":"g0-pbp-peer",
      "data":{"goalieId":"8478499","samplePeerPopulationId":"same-cohort-2026",
         "sourceClass":"INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY",
         "sourceType":"OFFICIAL_NHL_GOALIE_HISTORICAL_PBP_COORDINATE_PROXY_V1",
         "peerSampleNeverLeagueEDGEPercentile":True,"fullySourceComparedAreas":3,
         "weakZones":{"R Point":{"shotsAgainst":37,"goalsAgainst":3,
             "samplePeerSavePctgPercentile":.05,
             "peerComparedSameOrigin":True,"peerGoaliesSampled":15}},
         "strengthZones":{},"sample":{"allZoneObservations":125},
         "counterevidence":{"matchedPeerCohort":True}}}
    direction={"attacker":"DAL","defender":"VGK","gameId":"9000",
      "goalieProfileEvidenced":True,
      "g0SelectionMethod":"ALL_SOURCE_REVIEWED_STARTER_PAIRS_AGREE",
      "g0DecisionProof":{"pairwiseReceipts":[{
          "attacker":"DAL","goalieA":"8478499","goalieB":"8479979",
          "sourceDecisionMethod":"SAME_HISTORICAL_OFFICIAL_PBP_GOALIE_PEER_POOL",
          "proof":{"samePeerPopulationId":"same-cohort-2026",
             "sourceCoherentIndependentHistoricalSample":True}}]},
      "targetGoalies":[{"goalieId":"8478499"}]}
    game={"id":"9000","away":"DAL","home":"VGK",
         "goaliePeerContexts":{"8478499":peer}}
    return game,direction,starter

def test_original_g0_pbp_evidence_is_reused_for_the_exact_deciding_goalie():
    game,chosen,starter=g0_scene()
    linked=g0_source_coherent_scorer_goalie(game,chosen,starter)
    assert linked is not starter
    assert "R Point" in linked["data"]["weakZones"]
    assert linked["data"]["sourceCoherentG0ToG5"] is True
    assert linked["data"]["goalieProfileSourceUrl"]==SRC
    assert linked["data"]["status"]=="EXPECTED"
    assert linked["data"]["goalieId"]=="8478499"
    assert starter["data"]["weakZones"]=={}  # unchanged NHL EDGE receipt

def test_g0_never_fakes_a_missing_mismatched_or_unverified_peer_receipt():
    game,chosen,starter=g0_scene()
    game["goaliePeerContexts"]["8478499"]["data"]["samplePeerPopulationId"]="wrong"
    assert g0_source_coherent_scorer_goalie(game,chosen,starter) is starter
    game,chosen,starter=g0_scene()
    game["goaliePeerContexts"]["8478499"]["data"]["weakZones"]["R Point"]["shotsAgainst"]=2
    assert g0_source_coherent_scorer_goalie(game,chosen,starter) is starter
    game,chosen,starter=g0_scene()
    chosen.pop("g0DecisionProof")
    assert g0_source_coherent_scorer_goalie(game,chosen,starter) is starter
    game,chosen,starter=g0_scene()
    chosen["g0SelectionMethod"]="SOURCE_WEAK_ZONE_SET_CONTAINMENT"
    assert g0_source_coherent_scorer_goalie(game,chosen,starter) is starter

def test_independent_on_net_defensive_concession_unblocks_a_genuine_g9_lane(tmp_path):
    # The target genuinely allows MORE on-net L-circle shots per game than
    # seven independent peers, even though it allows fewer total attempts.
    events=[];meta={};eid=0
    def make_game(gid,defender_id,defender_name,owner_id,zone_attempts,shots):
        nonlocal eid
        meta[gid]={"homeTeamId":str(defender_id),"awayTeamId":str(owner_id),
           "homeAbbrev":defender_name,"awayAbbrev":"OPP"}
        for zone,n in zone_attempts.items():
            x,y=(64,22) if zone=="L Circle" else (83,4)
            for i in range(n):
                eid+=1
                events.append({"gameId":gid,"eventId":str(eid),
                  "ownerTeamId":str(owner_id),"x":x,"y":y,
                  "type":"shot-on-goal" if i<shots.get(zone,0) else "missed-shot",
                  "sourceUrl":SRC})
    for i in range(8):
        make_game("target-"+str(i),10,"PHI",1000+i,
                  {"L Circle":2,"Low Slot":20},{"L Circle":2,"Low Slot":8})
    for t in range(7):
        for i in range(8):
            make_game(f"peer-{t}-{i}",200+t,f"P{t}",2000+t*20+i,
                      {"L Circle":4,"Low Slot":16},{"L Circle":1,"Low Slot":8})
    con=open_db(str(tmp_path/"defense.sqlite"))
    try:
        snapshot={"games":[{"id":"real-game","away":"BUF","home":"PHI"}]}
        result=make_coverage(con,snapshot,DATE,"PROJECTED",events,meta)
        assert result["coverageAttackSides"]>=1
        row=con.execute("SELECT payload FROM evidence WHERE kind='TEAM_COVERAGE' AND game_id='real-game'").fetchone()
        cov=json.loads(row["payload"])
        zone=cov["zoneConcessions"]["L Circle"]
        assert zone["attemptsPerGame"]<zone["peerMedianAttemptsPerGame"]
        assert zone["onNetShotsPerGame"]>zone["peerMedianOnNetShotsPerGame"]
        assert zone["positiveConcessionBases"]==["ON_NET_SHOTS_AGAINST_PEER"]
        assert "L Circle" in cov["greenWeakZones"]
        assert cov["redStrongZones"]==[]
        proof={"shooterZone":"L Circle","greenTarget":cov["greenWeakZones"],
            "redAvoid":cov["redStrongZones"],"coverageSourceType":cov["sourceType"],
            "coverageComparison":cov["comparison"],"zoneConcessionEvidence":zone,
            "lowShotVolumeNotStrengthEvidence":cov["lowShotVolumeIsNotEvidenceOfDefensiveStrength"]}
        assert audit_gate("G9",proof,[SRC],"PROJECTED")==[]
        broken={**zone,"onNetShotsPerGame":0}
        assert "G9_POSITIVE_PER_GAME_CONCESSION_PROOF_MISSING" in audit_gate(
             "G9",{**proof,"zoneConcessionEvidence":broken},[SRC],"PROJECTED")
    finally:
        con.close()
