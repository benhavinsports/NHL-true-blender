"""Labels are outcomes of the source-proven scoring route, never filled quotas."""
from nhl_true_blender_engine.engine import (
    adjudicate_scoring_path,challenger_proof,MASTER,execute)
from nhl_true_blender_engine.tests.test_engine import evidence,skater,snapshot,DATE
from nhl_true_blender_engine.storage import open_db

def _decision(player=None,rivals=None,goalie=None,coverage=None,who=False):
    p=player or skater(2001,"slot",28,4)
    others=rivals if rivals is not None else [skater(2002,"slot",12,1)]
    g=goalie or evidence({"goalieId":"g123","status":"EXPECTED",
                          "weakZones":{"slot":{"shotsAgainst":80}}})
    c=coverage or evidence({"greenWeakZones":["slot"]})
    g10,rows=challenger_proof(p,others,g["data"]["weakZones"])
    dispositions={gate:{"disposition":"PASS"} for gate in MASTER[:-1]}
    assert g10 is True
    return adjudicate_scoring_path(p,[p,*others],
        p["release"]["data"],g,c,dispositions,rows,who)

def test_direct_primary_has_positive_receipts_not_fallback():
    path,proof=_decision()
    assert path=="PRIMARY"
    assert proof["fallbackToPrimary"] is False
    assert proof["positiveDirectGateEvidence"]["independentDefenseAreaDirectlyMatched"] is True
    assert proof["G10_5DisplacedPrimaryEvidence"]
    assert proof["pathQuotaApplied"] is False

def test_evidence_backed_who_emerges_without_a_who_quota():
    p=skater(2001,"slot",28,4,who=True)
    path,proof=_decision(player=p,who=True)
    assert path=="WHO"
    assert proof["G14IndependentWhoAnomalyVerified"] is True
    assert proof["whoPhysicalMechanism"]=="blue line chaos goal"
    assert proof["pathQuotaApplied"] is False
    direct_path,_=_decision()
    assert direct_path=="PRIMARY"

def test_secondary_route_that_defeats_documented_primary_is_a_transfer():
    p=skater(2001,"slot",25,4)
    p["release"]["data"].update({
        "originalPrimaryOrigin":"High Slot",
        "g0MatchedOwnOriginRoute":True,
        "g9DefensiveLaneIndependentlyMatched":True})
    rival=skater(2002,"slot",20,2)
    path,proof=_decision(player=p,rivals=[rival])
    assert path=="TRANSFER"
    assert proof["laneChangedAfterGoalieFirstG0"] is True
    assert proof["independentTransferDerivedFromG0AndG10_5"] is True
    assert proof["G10_5DisplacedPrimaryEvidence"][0]["displacedDirectPrimaryPlayerId"]=="2002"

def test_competing_source_proven_who_and_transfer_paths_are_not_arbitrarily_labeled():
    p=skater(2001,"slot",25,4,who=True)
    p["release"]["data"].update({
        "originalPrimaryOrigin":"High Slot",
        "g0MatchedOwnOriginRoute":True})
    rival=skater(2002,"slot",20,2)
    path,proof=_decision(player=p,rivals=[rival],who=True)
    assert path is None
    assert proof["competingWHOandTRANSFERPathsUnseparated"] is True
    assert proof["G14IndependentWhoAnomalyVerified"] is True
    assert proof["independentTransferDerivedFromG0AndG10_5"] is True
    assert proof["pathQuotaApplied"] is False

def test_lane_change_without_defeated_competing_recipient_remains_direct_primary():
    # Complete master definition: a lane change alone is not TRANSFER.
    # The other player's Point route never competes for this slot recipient.
    p=skater(2001,"slot",25,4)
    p["release"]["data"]["originalPrimaryOrigin"]="High Slot"
    rival=skater(2002,"Point",12,2)
    path,proof=_decision(player=p,rivals=[rival])
    assert path=="PRIMARY"
    assert proof["laneChangedAfterGoalieFirstG0"] is True
    assert proof["offUsualLaneTransferIntoGoalieWeakLane"] is False
    assert proof["laneChangeAloneDoesNotProveRecipientTransfer"] is True
    assert proof["independentTransferDerivedFromG0AndG10_5"] is False
    assert proof["fallbackToPrimary"] is False

def test_off_lane_route_without_every_direct_gate_gets_no_forced_label():
    p=skater(2001,"slot",25,4)
    p["release"]["data"]["originalPrimaryOrigin"]="High Slot"
    others=[skater(2002,"Point",12,2)]
    g=evidence({"goalieId":"g123","status":"EXPECTED","weakZones":{"slot":{"shotsAgainst":80}}})
    c=evidence({"greenWeakZones":["slot"]})
    _,rows=challenger_proof(p,others,g["data"]["weakZones"])
    d={gate:{"disposition":"PASS"} for gate in MASTER[:-1]}
    d["G16"]={"disposition":"NOT_EXECUTED"}
    path,proof=adjudicate_scoring_path(p,[p,*others],p["release"]["data"],g,c,d,rows,False)
    assert path is None
    assert proof["offUsualLaneTransferIntoGoalieWeakLane"] is False
    assert proof["fallbackToPrimary"] is False

def test_false_transfer_flag_does_not_get_label_without_g105_displaced_recipient():
    p=skater(2001,"slot",28,4)
    p["transferEvidence"]=evidence({
        "directRouteDisplaced":True,
        "routeZone":"slot",
        "displacedPlayerId":"not-the-actual-same-lane-rival"})
    path,proof=_decision(player=p)
    assert path is None
    assert proof["explicitDisplacementSourceValidated"] is False

def test_no_label_quota_three_independently_direct_players_stay_three_primaries(tmp_path):
    con=open_db(str(tmp_path/"evidence.sqlite"))
    s=snapshot(3)
    s["games"][2]["rosters"]["T3A"]["data"]["players"][0].pop("whoAnomaly",None)
    result=execute(con,s,DATE,"CONFIRMED")
    assert result["card"],result["errors"]
    assert [leg["path"] for leg in result["card"]["current_legs"]]==[
        "PRIMARY","PRIMARY","PRIMARY"]
    source=con.execute("""SELECT details FROM gates WHERE gate='G18' AND
                          player_id='1010'""").fetchone()
    assert '"fallbackToPrimary": false' in source["details"] or '"fallbackToPrimary":false' in source["details"]
    con.close()

