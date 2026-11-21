"""Next-day NHL.com preview: game identity and source-date integrity."""
from nhl_true_blender_engine.nhl_projected_goalies import (
    parse_projected_deployment, parse_projected_goalies,
    parse_official_unavailable, preview_urls,
)

DATE="2026-11-21"
GAME={"id":"2026020359","away":"EDM","home":"CAR",
      "rosters":{"EDM":{"data":{"players":[
          {"id":"1","name":"Filip Hallander","position":"C"},
          {"id":"2","name":"Connor McDavid","position":"C"},
          {"id":"3","name":"Kasperi Kapanen","position":"R"},
          {"id":"4","name":"Ryan Nugent-Hopkins","position":"C"},
      ],"goalies":[{"id":"10","name":"Tristan Jarry"},{"id":"11","name":"Devon Levi"}]}},
      "CAR":{"data":{"players":[
          {"id":"5","name":"William Carrier","position":"L"},
          {"id":"6","name":"Sebastian Aho","position":"C"},
          {"id":"7","name":"Andrei Svechnikov","position":"R"},
      ],"goalies":[{"id":"12","name":"Pyotr Kochetkov"},{"id":"13","name":"Brandon Bussi"}]}}}}
HTML="""<html><body>
<h1>Oilers at Hurricanes projected lineups</h1>
<p>By NHL.com</p><p>November 20, 2026</p>
<h2>Oilers projected lineup</h2>
<p>Filip Hallander -- Connor McDavid -- Kasperi Kapanen</p>
<p>Tristan Jarry</p>
<p>Devon Levi</p>
<p>Injured: Ryan Nugent-Hopkins (undisclosed)</p>
<h2>Hurricanes projected lineup</h2>
<p>William Carrier -- Sebastian Aho -- Andrei Svechnikov</p>
<p>Pyotr Kochetkov</p><p>Brandon Bussi</p>
<p>Scratched: None</p>
</body></html>"""

def test_exact_day_ahead_preview_accepts_projected_but_not_confirmed_units():
    url=preview_urls(GAME,DATE)[0]
    rows=parse_projected_deployment(HTML,GAME,DATE,url)
    assert {r["playerId"] for r in rows}=={"1","2","3","5","6","7"}
    assert {r["EV"] for r in rows}=={"F1"}
    assert all(r["status"]=="PROJECTED" and r["projectedNotConfirmed"] for r in rows)
    assert all(r["doesNotEstablishDressedOrPP"] for r in rows)
    starters=parse_projected_goalies(HTML,GAME,DATE,url)
    assert starters["EDM"]["goalieId"]=="10"
    assert starters["CAR"]["goalieId"]=="12"
    injuries=parse_official_unavailable(HTML,GAME,DATE,url)
    assert {(item["playerId"],item["status"]) for item in injuries}=={("4","INJURED")}

def test_no_future_day_promotion_from_generic_article_or_unrelated_url():
    generic="https://www.nhl.com/news/nhl-lineup-projections-2026-27-season"
    wrong="https://www.nhl.com/news/vegas-golden-knights-winnipeg-jets-game-preview-november-21-2026"
    for url in [None,generic,wrong,preview_urls(GAME,"2026-11-22")[0]]:
        assert not parse_projected_deployment(HTML,GAME,DATE,url)
        assert not parse_projected_goalies(HTML,GAME,DATE,url)
        assert not parse_official_unavailable(HTML,GAME,DATE,url)

def test_date_is_not_sufficient_if_article_describes_another_game():
    changed=HTML.replace("Oilers at Hurricanes projected lineups",
                         "Oilers at Flames projected lineups")
    url=preview_urls(GAME,DATE)[0]
    assert parse_projected_deployment(changed,GAME,DATE,url)==[]
    assert parse_projected_goalies(changed,GAME,DATE,url)=={}
    assert parse_official_unavailable(changed,GAME,DATE,url)==[]

def test_same_date_article_with_original_source_does_not_regress():
    current=HTML.replace("November 20, 2026","November 21, 2026")
    rows=parse_projected_deployment(current,GAME,DATE)
    assert len(rows)==6


def test_season_article_evidence_is_scoped_to_exact_saturday_matchup():
    article=HTML.replace("<h1>Oilers at Hurricanes projected lineups</h1>",
        "<h1>Projected lineups, starting goalies for today</h1>"
        "<h2>SATURDAY</h2>"
        "<h2>OILERS (17-4-3) at HURRICANES (16-3-3)</h2>")
    season_url="https://www.nhl.com/news/nhl-lineup-projections-2026-27-season"
    rows=parse_projected_deployment(article,GAME,DATE,season_url)
    assert {r["playerId"] for r in rows}=={"1","2","3","5","6","7"}
    assert all(r["status"]=="PROJECTED" for r in rows)
    assert parse_projected_goalies(article,GAME,DATE,season_url)["EDM"]["goalieId"]=="10"
    wrong_day=article.replace("<h2>SATURDAY</h2>","<h2>FRIDAY</h2>")
    wrong_match=article.replace("at HURRICANES", "at FLAMES")
    for changed in (wrong_day,wrong_match):
        assert parse_projected_deployment(changed,GAME,DATE,season_url)==[]
        assert parse_projected_goalies(changed,GAME,DATE,season_url)=={}
