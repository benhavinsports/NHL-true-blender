"""Source-separated G0/G9 own-lane ties must not be lost at G18.

These are synthetic route receipts, never published player selections.
"""
from nhl_true_blender_engine.engine import adjudicate_scoring_path
from nhl_true_blender_engine.tests.test_engine import evidence


SOURCE="https://api-web.nhle.com/v1/edge/skater-shot-location-detail/1000/now"


def scene(resolved):
    release={
        "archetype": "OBSERVED_OWN_SHOT_ORIGIN",
        "zone": "slot", "attempts": 7, "ownedGoals": 2,
        "originalPrimaryOrigin": "slot",
        "primaryWasTiedBeforeG0": True,
        "g0MatchedOwnOriginRoute": resolved,
        "g9DefensiveLaneIndependentlyMatched": resolved,
    }
    player={
        "id": "1000",
        "release": evidence(release, SOURCE),
        "finishOwnership": evidence(
            {"recipient": True, "creditedGoalsVerified": True}, SOURCE),
        "deployment": evidence({"EV": "F1", "status": "PROJECTED"}, SOURCE),
    }
    goalie=evidence({"weakZones": {"slot": {"goalsAgainst": 2}}},
        "https://api-web.nhle.com/v1/edge/goalie-shot-location-detail/2000/now")
    coverage=evidence({"greenWeakZones": ["slot"]},
        "https://api-web.nhle.com/v1/gamecenter/2026020001/play-by-play")
    gates={key: {"disposition": "PASS"} for key in
        ("G0", "G3", "G4", "G5", "G6", "G7", "G9", "G10",
         "G10.5", "G12", "G15", "G16", "G17")}
    return player,release,goalie,coverage,gates


def test_independent_g0_g9_lane_separation_permits_direct_primary():
    player,release,goalie,coverage,gates=scene(True)
    path,proof=adjudicate_scoring_path(
        player,[],release,goalie,coverage,gates,[],False)
    assert path=="PRIMARY", proof
    assert proof["primaryOriginIsSourceDistinct"] is True
    assert proof["positiveDirectGateEvidence"]["G0ThruG17SourcePass"] is True


def test_fully_passed_direct_recipient_is_not_rejected_for_old_preg0_lane_tie():
    # Positive goalie, defense, goal-credit, rival and contradiction gates
    # establish the scorer route, even if PRE-G0 primary origin was tied.
    player,release,goalie,coverage,gates=scene(False)
    path,proof=adjudicate_scoring_path(
        player,[],release,goalie,coverage,gates,[],False)
    assert path=="PRIMARY", proof
    assert proof["primaryOriginIsSourceDistinct"] is True
    assert proof["positiveDirectGateEvidence"]["G0ThruG17SourcePass"] is True


def test_unresolved_upstream_gate_never_gets_forced_primary():
    player,release,goalie,coverage,gates=scene(False)
    # An actual unresolved G9 blocks the direct route: an old pre-G0 tie
    # cannot be treated as proof of shooting into unmeasured defense.
    gates["G9"]["disposition"]="NOT_EXECUTED"
    path,proof=adjudicate_scoring_path(
        player,[],release,goalie,coverage,gates,[],False)
    assert path is None, proof
    assert proof["primaryOriginIsSourceDistinct"] is False


def test_entire_three_game_engine_carries_upstream_survivor_into_g18(tmp_path):
    # Integrated gate run, not a front-end card label or a monkeypatched PASS.
    from nhl_true_blender_engine.tests.test_engine import snapshot, DATE
    from nhl_true_blender_engine.storage import open_db
    from nhl_true_blender_engine.engine import execute
    import json
    snap=snapshot(3)
    first=snap["games"][0]
    skater=first["rosters"][first["away"]]["data"]["players"][0]
    release=skater["release"]["data"]
    release["primaryWasTiedBeforeG0"]=True
    release["originalPrimaryOrigin"]=release["zone"]
    # No convenient pre-G0 G0-matched flag is supplied. Every relevant gate
    # must independently pass as it would for real source-backed data.
    con=open_db(str(tmp_path/"survivor.sqlite"))
    try:
        result=execute(con,snap,DATE,"CONFIRMED")
        gid=str(first["id"]); pid=str(skater["id"])
        rows=con.execute(
            "SELECT gate,disposition FROM gates WHERE game_id=? AND player_id=?",
            (gid,pid)).fetchall()
        verdicts={row["gate"]:row["disposition"] for row in rows}
        assert len(verdicts)==20, verdicts
        assert all(outcome=="PASS" for outcome in verdicts.values()), verdicts
        assert result["uniqueGameSurvivors"]==3, result["errors"]
        assert result["card"] is not None, result["errors"]
        assert any(str(leg["gameId"])==gid and str(leg["playerId"])==pid
                   and leg["path"]=="PRIMARY"
                   for leg in result["card"]["current_legs"])
    finally:
        con.close()
