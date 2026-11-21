"""Live G6: independent NHL.com article time and matchup proof, not a stale date."""
from unittest.mock import patch
import deployment_sources as providers
from nhl_true_blender_engine.lineup_parser import dated_deployment_row

SOURCE_HTML = """<html><body>
<h1>Projected lineups, starting goalies for today</h1>
<div>By NHL.com</div><p>November 20, 2026</p>
<h2>SATURDAY</h2>
<h2>OILERS (17-4-3) at HURRICANES (16-3-3)</h2>
<h3>Oilers projected lineup</h3>
<p>Filip Hallander -- Connor McDavid -- Kasperi Kapanen</p>
<p>Vasily Podkolzin -- Leon Draisaitl -- Mathieu Joseph</p>
<p>Colton Dach -- Jason Dickinson -- Zach Hyman</p>
<p>Alex Formenton -- Owen Michaels -- Trent Frederic</p>
<h3>Hurricanes projected lineup</h3>
<p>William Carrier -- Sebastian Aho -- Andrei Svechnikov</p>
</body></html>"""

def test_early_published_nhl_article_can_verify_actual_next_day_game():
    with patch.object(providers, 'get', return_value=type('Response', (), {'text': SOURCE_HTML})()):
        rows,meta=providers.fetch_nhl_article(
            'EDM','edmonton-oilers','2026-11-21','carolina-hurricanes')
    assert meta['sourceDate']=='2026-11-21'
    assert meta['dateVerified'] is True
    assert {r['playerName'] for r in rows} >= {'Connor McDavid','Leon Draisaitl','Zach Hyman'}
    assert rows[0]['sourceTeam']=='EDM'
    assert all(r['powerPlayUnit'] is None for r in rows)
    proof=[{'value':rows[0]['line'],'sourceDate':meta['sourceDate'],
            'dateVerified':meta['dateVerified'],'sourceUrl':meta['url']}]
    assert dated_deployment_row({'lineEvidence':proof},'2026-11-21')['line']==1

def test_wrong_game_and_day_never_redate_nhl_article():
    for date, opponent in (
        ('2026-11-21','vegas-golden-knights'),
        ('2026-11-22','carolina-hurricanes'),
        ('2026-11-28','carolina-hurricanes'),
        ('2026-11-19','carolina-hurricanes'),
    ):
        with patch.object(providers, 'get', return_value=type('Response', (), {'text': SOURCE_HTML})()):
            rows,meta=providers.fetch_nhl_article('EDM','edmonton-oilers',date,opponent)
        assert rows  # research may remain available, never dated deployment
        assert meta['sourceDate'] is None
        assert meta['dateVerified'] is False
        proof=[{'value':1,'sourceDate':meta['sourceDate'],
                'dateVerified':meta['dateVerified'],'sourceUrl':meta['url']}]
        assert dated_deployment_row({'lineEvidence':proof},date)['line'] is None

def test_publication_date_alone_never_confirms_slate():
    with patch.object(providers, 'get', return_value=type('Response', (), {'text': SOURCE_HTML.replace('<h2>SATURDAY</h2>', '<h2>FRIDAY</h2>')})()):
        _,meta=providers.fetch_nhl_article('EDM','edmonton-oilers','2026-11-21','carolina-hurricanes')
    assert meta['dateVerified'] is False
