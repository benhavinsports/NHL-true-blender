"""MoneyPuck CSV refresh must NEVER crash an autonomous rerun.

All CSVs are synthetic fixtures. A changed same-day provider observation
gets a new immutable receipt instead of overwriting the old one. An identical
rerun is idempotent and maintains the one authoritative slate/card.
"""
import csv
import json
from pathlib import Path

from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.moneypuck_import import import_moneypuck

DATE="2026-11-16"
GAME="2026020331"

def write(path,rows):
    with open(path,"w",newline="",encoding="utf-8") as fh:
        out=csv.DictWriter(fh,fieldnames=list(rows[0]))
        out.writeheader()
        out.writerows(rows)

def load_csvs(directory,goals=2,team_shots=10):
    write(directory/"goalies.csv",[
        {"season":2026,"playerId":99,"team":"NYR","situation":"all"}])
    write(directory/"skaters.csv",[
        {"season":2026,"playerId":100,"team":"MTL","situation":"all",
         "I_F_shotAttempts":24,"I_F_shotsOnGoal":12,"I_F_xGoals":2.2,
         "I_F_highDangerShots":3,"games_played":8,
         "I_F_goals":goals,"I_F_primaryAssists":4}])
    write(directory/"teams.csv",[
        {"season":2026,"team":t,"situation":"5on5",
         "highDangerShotsAgainst":team_shots,
         "highDangerGoalsAgainst":2,"mediumDangerShotsAgainst":22,
         "lowDangerShotsAgainst":48}
        for t in ["MTL","NYR"]])
    write(directory/"lines.csv",[{"season":2026,"team":"MTL","situation":"5on5"}])

def snapshot():
    return {"games":[{
        "id":GAME,"away":"MTL","home":"NYR",
        "rosters":{"MTL":{"data":{"players":[{"id":100,"name":"Synthetic Shooter"}]}},
                   "NYR":{"data":{"players":[]}}}}]}

def test_identical_replay_idempotent_but_provider_stat_revision_preserved(tmp_path):
    con=open_db(str(tmp_path/"ledger.sqlite"))
    load_csvs(tmp_path,goals=2,team_shots=10)
    params=(con,snapshot(),DATE,"PROJECTED",tmp_path,DATE)
    one=import_moneypuck(*params)
    assert one["imported"]["PLAYER_FINISH_CREDIT"]==1
    initial=con.execute(
        "SELECT evidence_id,payload FROM evidence WHERE evidence_id LIKE 'mp-%'").fetchall()
    assert len(initial)==4
    assert len({x["evidence_id"] for x in initial})==4
    initial_goals=sorted(json.loads(x["payload"])["ownedGoals"]
        for x in initial if "PLAYER_FINISH_CREDIT" in x["evidence_id"])
    assert initial_goals==[2.0]
    # Multiple scheduled executions with the same data do not manufacture
    # new evidence or conflict with the ledger's immutable primary key.
    import_moneypuck(*params)
    assert con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]==4
    # Same slate/phase/provider, but MoneyPuck revised original observations.
    load_csvs(tmp_path,goals=3,team_shots=11)
    import_moneypuck(*params)
    rows=con.execute("SELECT evidence_id,payload FROM evidence WHERE kind='PLAYER_FINISH_CREDIT'").fetchall()
    assert len(rows)==2
    assert sorted(json.loads(x["payload"])["ownedGoals"] for x in rows)==[2.0,3.0]
    assert len({x["evidence_id"] for x in rows})==2
    # Both teams' aggregate revisions also remain separate and traceable.
    assert con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]==7
    import_moneypuck(*params)
    assert con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]==7
    con.close()
