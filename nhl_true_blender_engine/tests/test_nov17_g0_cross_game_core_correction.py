"""Correct the Nov 17 original Core only when CURRENT G0 invalidates its old side.

Synthetic independent source receipts; the test never names or selects a
real scorer. The actual G16/G18 pipeline must choose every replacement first.
"""
import json
from datetime import datetime, timezone

from nhl_true_blender_engine.engine import MASTER, build_verified_replacement
from nhl_true_blender_engine.storage import (
    fingerprint, get_card, open_db, record_evidence, save_card,
)

DATE="2026-11-17"
URL="https://api-web.nhle.com/v1/edge/goalie-shot-location-detail/{}/now"
SOURCE="https://api-web.nhle.com/v1/edge/skater-shot-location-detail/777/now"


def leg(game, pid):
    return {
        "gameId":str(game),"playerId":str(pid),
        "player":"Synthetic "+str(pid),"path":"PRIMARY",
        "sourceIds":[SOURCE],
        "gameState":"FUT","startUTC":"2099-11-18T00:00:00Z",
        "opposingGoalieId":"G-OLD" if game==105 else "G-OTHER",
    }


def receipt(con, eid, game, goalie=None, player=None, kind="GOALIE_PROFILE", url=None):
    source=url or URL.format(goalie or "old")
    record_evidence(con,{
        "evidence_id":eid,"slate_date":DATE,"stage":"PROJECTED",
        "game_id":str(game),"player_id":str(player) if player else None,
        "kind":kind,"source_url":source,
        "observed_at":"2026-11-17T15:45:00Z",
        "payload":{"goalieId":goalie} if goalie else {"ownRouteVerified":True},
    })


def fixture(tmp_path):
    con=open_db(str(tmp_path/"original.sqlite"))
    previous=[leg(101,1),leg(102,2),leg(103,3)]
    initial=save_card(con,DATE,"PROJECTED",previous,11,
        now=datetime(2026,11,17,12,tzinfo=timezone.utc))
    con.execute("""CREATE TABLE card_retractions(
        slate_date TEXT PRIMARY KEY, card_id TEXT NOT NULL,
        original_fingerprint TEXT NOT NULL, retraction_reason TEXT NOT NULL,
        original_card TEXT NOT NULL, original_versions TEXT NOT NULL,
        upstream_survivors TEXT NOT NULL, retracted_at_utc TEXT NOT NULL)""")
    con.execute("INSERT INTO card_retractions VALUES(?,?,?,?,?,?,?,?)",
        (DATE,initial["card_id"],initial["fingerprint"],
         "USER_EXPLICITLY_RETRACTED_INVALID_G18","{}","[]","[]",
         "2026-11-17T14:00:00Z"))
    receipt(con,"old-initial",102,"G-START")
    receipt(con,"reissue-trigger",105,"G-OLD")
    receipt(con,"reissue-g17",105,None,5,"G17_CONTRADICTION",SOURCE)
    revised=[leg(101,1),leg(105,5),leg(103,3)]
    initial_replacement={
        "baselineFingerprint":initial["fingerprint"],
        "triggerEvidenceId":"reissue-trigger",
        "oldValue":{"gameId":"102"},"newValue":{"gameId":"105"},
        "affectedGates":["G0"],"dependentGates":["G0","G10.5","G17","G18"],
        "priorSurvivorFailure":{"failedGate":"G0","sourceIds":["old-initial"]},
        "g105EveryChallenger":{"comparisonRows":[{"status":"DEFEATED"}]},
        "g17Contradictions":{"sourceIds":["reissue-g17"]},
        "newFingerprint":fingerprint(revised),
    }
    existing=save_card(con,DATE,"PROJECTED",revised,11,
        audit=initial_replacement,now=datetime(2026,11,17,15,tzinfo=timezone.utc))
    assert existing["revision"]==2
    receipt(con,"g0-previous-scope",105,"G-OLD")
    receipt(con,"g0-new-selected",105,"G-NEW")
    receipt(con,"new-direct-release",104,None,4,"SKATER_SHOT_ORIGIN",SOURCE)
    receipt(con,"new-contradiction",104,None,4,"G17_CONTRADICTION",SOURCE)
    new_legs=[leg(101,1),leg(104,4),leg(103,3)]
    scan=[
        {"gameId":"105","attacker":"OLD-TEAM","defender":"NEW-TEAM",
         "goalieProfileEvidenced":True,"targetGoalies":[{
             "goalieId":"G-OLD","profileReviewed":True,
             "goalieProfileEvidenceId":"g0-previous-scope",
             "goalieProfileSourceUrl":URL.format("G-OLD"),
         }]},
        {"gameId":"105","attacker":"NEW-TEAM","defender":"OLD-TEAM",
         "goalieProfileEvidenced":True,"targetGoalies":[{
             "goalieId":"G-NEW","profileReviewed":True,
             "goalieProfileEvidenceId":"g0-new-selected",
             "goalieProfileSourceUrl":URL.format("G-NEW"),
         }]},
    ]
    directions={"105":{**scan[1],
        "g0SelectionMethod":"NHL_EDGE_SOURCE_PEER_PERCENTILE_CROSS_ORIGIN_G0",
        "g0SelectedOnlyAfterBothStarterProfiles":True,
        "g0DecisionProof":{"oppositeDirectionSourceReviewed":True,
           "goalieSourceUrls":[URL.format("G-OLD"),URL.format("G-NEW")],
           "noWeightsOrExternalOdds":True},
    }}
    def selected(legs):
        result=[]
        for x in legs:
            cand={
                "player":{
                    "id":x["playerId"],"name":x["player"],
                    "release":{"evidenceId":"new-direct-release"},
                    "contradictions":{"evidenceId":"new-contradiction"},
                },
                "complete":True,
                "dispositions":{g:{"disposition":"PASS","details":{"sourceIds":[SOURCE]}}
                                for g in MASTER},
                "challengers":[{"challengerId":"909","status":"DEFEATED",
                                 "sourceUrls":[SOURCE]}],
            }
            result.append({"game":{"id":x["gameId"]},"candidate":cand})
        return result
    return con,existing,new_legs,selected(new_legs),scan,directions


def test_legitimate_g0_reversal_cross_game_corrects_only_one_verified_original_leg(tmp_path):
    con,old,legs,chosen,scan,directions=fixture(tmp_path)
    try:
        audit=build_verified_replacement(
            con,old,legs,chosen,DATE,"PROJECTED",
            scan=scan,selected_directions=directions)
        assert audit is not None
        assert audit["exceptionScope"]=="NOV17_RETRACTED_SLATE_G0_SOURCE_REVERSAL"
        assert audit["priorSurvivorFailure"]["failedGate"]=="G0"
        assert audit["priorSurvivorFailure"]["currentVerifiedAttacker"]=="NEW-TEAM"
        assert audit["priorSurvivorFailure"]["previousAttacker"]=="OLD-TEAM"
        assert audit["priorSurvivorFailure"]["sourceIds"]==[
            "g0-previous-scope","g0-new-selected"]
        assert audit["fullG16G18DecisionsAlreadyExecuted"] is True
        assert audit["manualReplacementForbidden"] is True
        saved=save_card(con,DATE,"PROJECTED",legs,11,audit=audit,
            now=datetime(2026,11,17,18,tzinfo=timezone.utc))
        assert saved["revision"]==3
        assert saved["current_legs"]==legs
        assert saved["initial_legs"]==old["initial_legs"]
        assert saved["card_id"]==old["card_id"]
        stored=con.execute("SELECT rationale FROM card_versions WHERE "
                           "slate_date=? AND revision=3",(DATE,)).fetchone()
        assert json.loads(stored["rationale"])["audit"]["priorSurvivorFailure"]["failedGate"]=="G0"
        assert con.execute("SELECT COUNT(*) FROM card_retractions").fetchone()[0]==1
    finally:
        con.close()


def test_cannot_replace_when_old_g0_side_is_still_selected(tmp_path):
    con,old,legs,chosen,scan,directions=fixture(tmp_path)
    try:
        directions["105"]={**directions["105"],
             "attacker":"OLD-TEAM","defender":"NEW-TEAM"}
        assert build_verified_replacement(con,old,legs,chosen,DATE,"PROJECTED",
            scan=scan,selected_directions=directions) is None
        assert get_card(con,DATE)["current_legs"]==old["current_legs"]
    finally:con.close()


def test_cannot_replace_with_missing_goalie_source_identity(tmp_path):
    con,old,legs,chosen,scan,directions=fixture(tmp_path)
    try:
        scan[0]["targetGoalies"][0]["goalieProfileEvidenceId"]="fake-id"
        assert build_verified_replacement(con,old,legs,chosen,DATE,"PROJECTED",
            scan=scan,selected_directions=directions) is None
    finally:con.close()


def test_cannot_replace_with_failed_g17_or_unverified_new_candidate(tmp_path):
    con,old,legs,chosen,scan,directions=fixture(tmp_path)
    try:
        chosen[1]["candidate"]["dispositions"]["G17"]["disposition"]="NOT_EXECUTED"
        assert build_verified_replacement(con,old,legs,chosen,DATE,"PROJECTED",
            scan=scan,selected_directions=directions) is None
        chosen[1]["candidate"]["dispositions"]["G17"]["disposition"]="PASS"
        chosen[1]["candidate"]["player"]["contradictions"]["evidenceId"]="unverified"
        assert build_verified_replacement(con,old,legs,chosen,DATE,"PROJECTED",
            scan=scan,selected_directions=directions) is None
    finally:con.close()


def test_no_previous_user_retraction_and_no_multiple_or_after_puck_replacement(tmp_path):
    con,old,legs,chosen,scan,directions=fixture(tmp_path)
    try:
        con.execute("DELETE FROM card_retractions")
        assert build_verified_replacement(con,old,legs,chosen,DATE,"PROJECTED",
            scan=scan,selected_directions=directions) is None
        con.execute("INSERT INTO card_retractions VALUES(?,?,?,?,?,?,?,?)",
            (DATE,old["card_id"],old["initial_legs"][0]["gameId"]+"-oldhash",
             "USER_RETRACTED","{}","[]","[]","2026-11-17T14:00:00Z"))
        proposed=[leg(106,6),leg(104,4),leg(103,3)]
        assert build_verified_replacement(con,old,proposed,chosen,DATE,"PROJECTED",
            scan=scan,selected_directions=directions) is None
        audit=build_verified_replacement(con,old,legs,chosen,DATE,"PROJECTED",
            scan=scan,selected_directions=directions)
        assert audit is not None
        try:
            save_card(con,DATE,"PROJECTED",legs,11,audit=audit,
                now=datetime(2100,1,1,tzinfo=timezone.utc))
            assert False,"Frozen card was modified after puck drop"
        except ValueError as exc:
            assert "puck drop" in str(exc).lower() or "frozen" in str(exc).lower()
    finally:con.close()


def test_cross_game_source_exception_never_applies_to_another_slate(tmp_path):
    con,old,legs,chosen,scan,directions=fixture(tmp_path)
    try:
        assert build_verified_replacement(con,old,legs,chosen,"2026-11-18","PROJECTED",
            scan=scan,selected_directions=directions) is None
    finally:con.close()
