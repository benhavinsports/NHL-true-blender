"""An extra G0-unseparated game remains in audit, not a failure of three verified games."""
from nhl_true_blender_engine.engine import execute
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import snapshot,DATE

def test_nonselected_unresolved_goalie_direction_does_not_invalidate_locked_core(tmp_path):
    con=open_db(str(tmp_path/"other.sqlite"))
    s=snapshot(4)
    g=s["games"][3]
    # Neither attack direction has a sourced opposing goalie profile.
    g["goalies"][g["home"]]=[]
    g["goalies"][g["away"]]=[]
    result=execute(con,s,DATE,"CONFIRMED")
    assert result["card"] is not None,result["errors"]
    assert len(result["card"]["current_legs"])==3
    assert len({r["gameId"] for r in result["card"]["current_legs"]})==3
    assert result["errors"]==[]
    assert len(result["nonselectedGameResearchNotes"])==1
    assert str(g["id"]) in result["nonselectedGameResearchNotes"][0]
    assert result["nonselectedGameResearchNeverReplacesLockedCore"] is True
    # The failed goalie direction remains in the actual source record.
    assert result["g0Directions"]==8
    assert result["g0Complete"]==6
    assert con.execute("""SELECT COUNT(*) FROM gates WHERE slate_date=?
        AND game_id=? AND gate='G0' AND disposition='NOT_EXECUTED'""",
        (DATE,str(g["id"]))).fetchone()[0]==2
    con.close()

def test_g0_failure_still_blocks_publication_when_three_games_cannot_survive(tmp_path):
    con=open_db(str(tmp_path/"short.sqlite"))
    s=snapshot(3)
    g=s["games"][2]
    g["goalies"][g["home"]]=[]
    result=execute(con,s,DATE,"CONFIRMED")
    assert result["card"] is None
    assert result["errors"]
    assert result["nonselectedGameResearchNotes"]==[]
    con.close()
