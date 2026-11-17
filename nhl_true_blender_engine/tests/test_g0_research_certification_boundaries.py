"""Branch-specific G0 research must never masquerade as scorer-eligible players.

These are official NHL roster identities evaluated in namespaced potential
goalie branches. Preserve every original master+overlay source receipt while
isolating them from the G0-authorized Core-candidate certification.
"""
from nhl_true_blender_engine.engine import execute,EXECUTION_ORDER
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.first_gate_audit import first_gate_audit
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import DATE,game,skater,evidence


def _goalie(gid,team):
    return evidence({"goalieId":gid,"team":team,"status":"EXPECTED",
                     "weakZones":{"slot":{"savePct":0.8}},
                     "sample":{"datedObservedShots":50},
                     "counterevidence":{"reviewedAreas":["slot"]}})


def test_unresolved_g0_research_keeps_every_gate_without_faking_candidate_pass(tmp_path):
    con=open_db(str(tmp_path/"g0_audit.sqlite"))
    g=game(1)
    g["goalies"][g["away"]]=[_goalie("one",g["away"])]
    g["goalies"][g["home"]]=[_goalie("two",g["home"]),
                              _goalie("three",g["home"])]
    g["rosters"][g["home"]]=evidence({
        "players":[skater(9842,"slot",18,2)]})
    result=execute(con,{"games":[g]},DATE,"PROJECTED")
    assert result["card"] is None
    assert result["eligibleSkaterRows"]==4  # four real roster IDs
    assert result["unresolvedG0ResearchBranchCount"]==7
    assert result["unresolvedG0PlayerSourceChecks"]==7*len(EXECUTION_ORDER)
    census=certify_gates(con,DATE,"PROJECTED",1)
    assert census["gateRows"]==7*len(EXECUTION_ORDER)+2
    assert census["scannedSkaters"]==0
    assert census["allOfficialSkatersReviewedIncludingG0Research"]==4
    assert census["g0ResearchOnlyOfficialSkaters"]==4
    assert census["g0ResearchOnlyBranchMatrices"]==7
    assert census["g0ResearchOnlyGateRows"]==7*len(EXECUTION_ORDER)
    assert not census["selectedCoreOnlyFullyCertified"]
    assert not census["allSkatersHaveEachGateRecord"]
    assert census["gateChecksAttempted"]=={g:0 for g in EXECUTION_ORDER}
    first=first_gate_audit(con,DATE,"PROJECTED")
    assert first["scannedSkaters"]==0
    assert first["g0ResearchOnlyBranchMatrices"]==7
    assert first["g0ResearchOnlyGateRows"]==7*len(EXECUTION_ORDER)
    assert "G0" not in first["firstNonpassingGateCounts"]
    con.close()


def test_true_g0_selected_skaters_not_mixed_with_unselected_necessary_research(tmp_path):
    from nhl_true_blender_engine.tests.test_engine import snapshot
    con=open_db(str(tmp_path/"selection.sqlite"))
    s=snapshot(4)
    g=s["games"][3]
    # Force G0 to remain uncertain even with real known goalie IDs.
    g["goalies"][g["away"]]=[_goalie("game4-away",g["away"])]
    g["goalies"][g["home"]]=[_goalie("game4-home",g["home"])]
    result=execute(con,s,DATE,"CONFIRMED")
    census=certify_gates(con,DATE,"CONFIRMED",4)
    assert census["scannedSkaters"]>0
    assert census["g0ResearchOnlyBranchMatrices"]>0
    assert (census["scannedSkaters"]+
            census["g0ResearchOnlyOfficialSkaters"]==
            census["allOfficialSkatersReviewedIncludingG0Research"])
    assert all(count==census["scannedSkaters"] for count in
               census["gateChecksAttempted"].values())
    assert census["g0ResearchOnlyGateRows"]==(
        census["g0ResearchOnlyBranchMatrices"]*len(EXECUTION_ORDER))
    # Research is a separate diagnostic channel, not extra G18 candidates.
    assert all("G0_RESEARCH:" not in str(row.get("playerId","")) for row
               in result["preCoreQualifiedSurvivors"])
    con.close()
