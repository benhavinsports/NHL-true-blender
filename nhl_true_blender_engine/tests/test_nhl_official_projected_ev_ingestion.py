"""NHL.com pregame line evidence must be player-ID exact and PROJECTED only."""
from nhl_true_blender_engine.nhl_projected_goalies import parse_projected_deployment


def _player(pid,name,pos):
    return {"id":str(pid),"name":name,"position":pos}

def _game():
    return {
        "away":"COL","home":"UTA",
        "rosters":{
            "COL":{"data":{"players":[
                _player(1,"Martin Necas","R"),
                _player(2,"Nathan MacKinnon","C"),
                _player(3,"Artturi Lehkonen","L"),
                _player(4,"Cale Makar","D"),
                _player(5,"Devon Toews","D")]}},
            "UTA":{"data":{"players":[
                _player(6,"Clayton Keller","L"),
                _player(7,"Logan Cooley","C"),
                _player(8,"Dylan Guenther","R")]}}
        }
    }

HTML = """
<h1>November 19, 2026</h1>
<h2>Avalanche projected lineup</h2>
<p>Martin Necas -- Nathan MacKinnon -- Artturi Lehkonen</p>
<p>Cale Makar -- Devon Toews</p>
<p>Scratched: Somebody Else</p>
<h2>Mammoth projected lineup</h2>
<p>Clayton Keller -- Logan Cooley -- Dylan Guenther</p>
<p>Status report</p>
"""

def test_exact_player_ids_and_source_projected_evidence():
    rows=parse_projected_deployment(HTML,_game(),"2026-11-19")
    ids={row["playerId"]:row["EV"] for row in rows}
    assert ids=={"1":"F1","2":"F1","3":"F1","4":"D1","5":"D1",
                 "6":"F1","7":"F1","8":"F1"}
    assert all(row["status"]=="PROJECTED" and row["projectedNotConfirmed"]
               and row["doesNotEstablishDressedOrPP"] for row in rows)

def test_wrong_date_cannot_become_tonight_deployment():
    assert parse_projected_deployment(HTML,_game(),"2026-11-20")==[]

def test_unmatched_player_does_not_generate_partial_line():
    game=_game()
    game["rosters"]["COL"]["data"]["players"][0]["name"]="Some Different Skater"
    rows=parse_projected_deployment(HTML,game,"2026-11-19")
    assert not any(row["playerId"] in ("1","2","3") for row in rows)
    assert any(row["playerId"]=="4" for row in rows)

def test_no_unrelated_name_match_or_double_assignment():
    html="""<h1>November 19, 2026</h1>
    <h2>Avalanche projected lineup</h2>
    <p>Martin Necas -- Nathan MacKinnon -- Artturi Lehkonen</p>
    <p>Martin Necas -- Nathan MacKinnon -- Artturi Lehkonen</p>"""
    rows=parse_projected_deployment(html,_game(),"2026-11-19")
    assert len(rows)==3
    assert len({r["playerId"] for r in rows})==3
