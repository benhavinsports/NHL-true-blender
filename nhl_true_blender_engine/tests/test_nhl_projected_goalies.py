"""NHL official projected goalie is evidence; never a fake confirmation."""
from nhl_true_blender_engine.nhl_projected_goalies import parse_projected_goalies,preview_urls,parse_official_unavailable
from nhl_true_blender_engine.enrichment import ingest,attach
from nhl_true_blender_engine.engine import all_goalie_branches
from nhl_true_blender_engine.storage import open_db

DATE="2026-11-16"
URL="https://www.nhl.com/news/vancouver-canucks-utah-mammoth-game-preview-november-16-2026"

def game():
    def team(*goalies):
        return {"data":{"players":[],"goalies":[{"id":str(i),"name":n} for i,n in goalies]}}
    return {"id":"2026020332","away":"VAN","home":"UTA",
            "rosters":{"VAN":team((1,"Nikita Tolopilo"),(2,"Kevin Lankinen")),
                       "UTA":team((3,"Karel Vejmelka"),(4,"Sebastian Cossa"))},
            "goalies":{"VAN":[],"UTA":[]},"coverage":{}}

def html():
    return """<html><body><main><article>
      <h1>Canucks at Mammoth projected lineups</h1>
      <p>November 16, 2026</p>
      <h2>Canucks projected lineup</h2>
      <p>Jake DeBrusk -- Elias Pettersson -- Jonathan Lekkerimaki</p>
      <p>Nikita Tolopilo</p><p>Kevin Lankinen</p>
      <p>Scratched: Leevi Merilainen</p>
      <h2>Mammoth projected lineup</h2>
      <p>Clayton Keller -- Vincent Trocheck -- Anders Lee</p>
      <p>Karel Vejmelka</p><p>Sebastian Cossa</p>
      <p>Injured: Logan Cooley</p>
    </article></main></body></html>"""

def test_source_parses_published_first_goalie_per_official_roster_without_confirmation():
    g=game()
    out=parse_projected_goalies(html(),g,DATE)
    assert out["VAN"]["goalieId"]=="1"
    assert out["UTA"]["goalieId"]=="3"
    assert URL in preview_urls(g,DATE)
    assert parse_projected_goalies(html(),g,"2026-11-15")=={}

def test_unambiguous_projected_goalie_not_permanently_forced_over_confirmation(tmp_path):
    g=game()
    con=open_db(str(tmp_path/"starter.sqlite"))
    now="2026-11-16T14:00:00+00:00"
    try:
        def add(team,pid,status,preferred=False):
            ingest(con,{"evidence_id":f"{team}-{pid}-{status}-{preferred}",
                "slate_date":DATE,"stage":"PROJECTED","game_id":g["id"],
                "kind":"GOALIE_STARTER","observed_at":now,"source_url":URL,
                "payload":{"team":team,"goalieId":str(pid),"status":status,
                           "projectedPreferred":preferred}})
        add("VAN",1,"EXPECTED");add("VAN",2,"EXPECTED")
        add("VAN",1,"EXPECTED",True)
        add("UTA",3,"EXPECTED");add("UTA",4,"EXPECTED")
        add("UTA",3,"EXPECTED",True)
        attach(con,{"games":[g]},DATE,"PROJECTED")
        options=all_goalie_branches(g,"PROJECTED")
        assert [b["data"]["goalieId"] for b in options["VAN"]]==["1"]
        assert [b["data"]["goalieId"] for b in options["UTA"]]==["3"]
        assert options["VAN"][0]["data"]["status"]=="EXPECTED"
        add("VAN",2,"CONFIRMED")
        g["goalies"]={"VAN":[],"UTA":[]}
        attach(con,{"games":[g]},DATE,"PROJECTED")
        assert [b["data"]["goalieId"] for b in all_goalie_branches(g,"PROJECTED")["VAN"]]==["2"]
    finally:
        con.close()

def test_conflicting_source_goaltenders_are_not_forced(tmp_path):
    g=game()
    con=open_db(str(tmp_path/"conflict.sqlite"))
    try:
        for pid in (1,2):
            ingest(con,{"evidence_id":f"reported-{pid}","slate_date":DATE,
              "stage":"PROJECTED","game_id":g["id"],"kind":"GOALIE_STARTER",
              "observed_at":"2026-11-16T13:00:00+00:00",
              "source_url":URL+"/source"+str(pid),
              "payload":{"team":"VAN","goalieId":str(pid),
                         "status":"EXPECTED","projectedPreferred":True}})
        attach(con,{"games":[g]},DATE,"PROJECTED")
        assert len(all_goalie_branches(g,"PROJECTED")["VAN"])==2
    finally:
        con.close()

def test_explicit_nhl_injured_scratch_names_resolve_to_official_skater_ids_only():
    g=game()
    g["rosters"]["VAN"]["data"]["players"]=[
        {"id":"101","name":"Arshdeep Bains","position":"L"},
        {"id":"102","name":"Guillaume Brisebois","position":"D"},
        {"id":"103","name":"Jake DeBrusk","position":"L"}]
    g["rosters"]["UTA"]["data"]["players"]=[
        {"id":"201","name":"Logan Cooley","position":"C"},
        {"id":"202","name":"Nick Schmaltz","position":"C"},
        {"id":"203","name":"Clayton Keller","position":"L"}]
    markup="""<html><main><h1>November 16, 2026</h1>
        <h2>Canucks projected lineup</h2>
        <p>Jake DeBrusk -- Elias Pettersson -- Jonathan Lekkerimaki</p>
        <p>Scratched: Arshdeep Bains, Leevi Merilainen</p>
        <p>Injured: Guillaume Brisebois (undisclosed)</p>
        <h2>Mammoth projected lineup</h2>
        <p>Clayton Keller -- Vincent Trocheck -- Anders Lee</p>
        <p>Injured: Logan Cooley (upper body), Nick Schmaltz (lower body)</p>
        <p>Status report</p></main></html>"""
    rows=parse_official_unavailable(markup,g,DATE)
    assert {(x["playerId"],x["status"]) for x in rows}=={
        ("101","SCRATCHED"),("102","INJURED"),
        ("201","INJURED"),("202","INJURED")}
    assert all(x["playerId"] not in ("1","2","3","4") for x in rows)
    assert parse_official_unavailable(markup,g,"2026-11-15")==[]
