"""Original G17 must independently review SAME G0-bound goalie source as scorer G5.

No manually selected scorer, fabricated contradiction outcomes, or copied PASS.
"""
import json
from nhl_true_blender_engine.engine import execute
from nhl_true_blender_engine.contradiction_review import review_all_candidates
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import snapshot,DATE,evidence
from nhl_true_blender_engine.tests.test_g0_to_g5_g9_live_route_repair import g0_scene,SRC

def test_missing_g17_review_is_acquired_by_full_engine_before_gate_decision(tmp_path):
    snap=snapshot()
    game=snap["games"][0]
    main=game["rosters"][game["away"]]["data"]["players"][0]
    assert "contradictions" in main
    del main["contradictions"]
    con=open_db(str(tmp_path/"repair.sqlite"))
    try:
        result=execute(con,snap,DATE,"CONFIRMED")
        player=str(main["id"])
        row=con.execute(
          "SELECT disposition,details FROM gates WHERE stage='CONFIRMED' "
          "AND game_id=? AND player_id=? AND gate='G17'",
          (game["id"],player)).fetchone()
        assert row is not None
        assert row["disposition"]=="PASS",row["details"]
        proof=json.loads(row["details"])["evidence"]
        assert proof["sourceDerivedReviewResolved"] is True
        assert proof["counterevidence"]["G0SelectionDoesNotCopyG17Verdict"] is True
        assert proof["counterevidence"]["goalieStrengthReview"]["matchedWeakAreas"]>=1
        assert proof["counterevidence"]["strongestRivalReview"]["everyRivalReviewed"] is True
        assert result["uniqueGameSurvivors"]==3
    finally:
        con.close()

def test_existing_independent_g17_reviews_are_not_overwritten(tmp_path):
    snap=snapshot()
    con=open_db(str(tmp_path/"unchanged.sqlite"))
    try:
        res=execute(con,snap,DATE,"CONFIRMED")
        assert res["uniqueGameSurvivors"]==3
        assert con.execute(
          "SELECT COUNT(*) FROM evidence WHERE kind='PLAYER_CONTRADICTIONS'"
        ).fetchone()[0]==0
    finally:
        con.close()

def test_source_coherent_g17_reviews_actual_pbp_goalie_id_and_own_origin(tmp_path):
    game,direction,starter=g0_scene()
    game["goalies"]={"VGK":[starter],"DAL":[]}
    game["date"]=DATE
    player={"id":"9001","name":"Independent observed scorer","position":"D",
      "availability":"PROJECTED_ACTIVE",
      "release":evidence({"archetype":"OFFICIAL_EDGE_OWN_ORIGIN",
           "zone":"R Point","attempts":7,"ownedGoals":1,
           "allRoutes":[{"zone":"R Point","sog":7,"ownedGoals":1}]},
           source="https://api-web.nhle.com/v1/edge/skater-shot-location-detail/9001/now"),
      "deployment":evidence({"EV":"D1","status":"PROJECTED","PP":"PP2"})}
    game["rosters"]={"DAL":evidence({"players":[player]}),
                     "VGK":evidence({"players":[]})}
    game["coverage"]={"DAL":evidence({"greenWeakZones":["R Point"]})}
    con=open_db(str(tmp_path/"source.sqlite"))
    try:
        before=review_all_candidates(con,{"games":[game]},DATE,"PROJECTED")
        assert before["unresolved"]==1 # source-stage PBP not yet linked to G0
        after=review_all_candidates(con,{"games":[game]},DATE,"PROJECTED",
                                    selected_directions={str(game["id"]):direction})
        assert after["reviewedSkaters"]==1
        assert after["unresolved"]==0
        reviews=con.execute(
          "SELECT payload FROM evidence WHERE kind='PLAYER_CONTRADICTIONS' "
          "ORDER BY observed_at, rowid").fetchall()
        assert len(reviews)==2
        last=json.loads(reviews[-1]["payload"])
        assert last["unresolved"] is False
        assert last["currentRinkOrigin"]=="R Point"
        assert last["sameIndependentlySelectedG0GoalieSourceAsScorerG5"] is True
        assert last["goalieStrengthReview"]["source"][0]["goalieId"]=="8478499"
        assert last["goalieStrengthReview"]["source"][0]["physicalOriginMatch"] is True
        assert SRC in last["sourceUrls"]
    finally:
        con.close()

def test_g17_does_not_reopen_g10_5_defeated_roster_candidates(monkeypatch,tmp_path):
    """G17 audits remaining contradictions; it must not rerun a defeated
    G10.5 teammate as though that earlier recipient decision never happened.
    """
    from nhl_true_blender_engine import contradiction_review
    snap=snapshot()
    con=open_db(str(tmp_path/"g17-live-rivals.sqlite"))
    original=contradiction_review.review_all_candidates
    calls=[]
    def capture(*args,**kwargs):
        calls.append((
            set(str(x) for x in (kwargs.get("only_player_ids") or ())),
            set(str(x) for x in (kwargs.get("eliminated_player_ids") or ())),
        ))
        return original(*args,**kwargs)
    monkeypatch.setattr(contradiction_review,"review_all_candidates",capture)
    try:
        result=execute(con,snap,DATE,"CONFIRMED")
        assert result["uniqueGameSurvivors"]==3
        checked=0
        for row in con.execute(
            "SELECT player_id,details FROM gates WHERE slate_date=? "
            "AND stage='CONFIRMED' AND gate='G10.5' AND disposition='PASS'",
            (DATE,),
        ):
            player_id=str(row["player_id"])
            evidence=json.loads(row["details"])["evidence"]
            resolved={
                str(item["challengerId"])
                for item in evidence.get("comparisonRows",[])
                if item.get("status") in (
                    "DEFEATED","SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE",
                    "DIFFERENT_TARGET_LANE")
            }
            if not resolved:
                continue
            matching=[excluded for only,excluded in calls if only=={player_id}]
            assert matching, f"G17 review was not observed for {player_id}"
            assert resolved <= matching[-1], (
                f"G17 reopened G10.5-resolved rivals for {player_id}: "
                f"{sorted(resolved-matching[-1])}"
            )
            checked+=1
        assert checked>0
    finally:
        con.close()
