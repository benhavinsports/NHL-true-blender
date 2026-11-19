"""Offline tests for official article deployment, time, and player-ID boundaries."""
from datetime import timezone
from scripts.ingest_nhl_historical_previews import (
    Article, id_index, normalize, preview_url, publication_clock, read_lines, utc)


SAMPLE = """
<html><head>
<meta property="article:published_time" content="2026-09-29T12:20:00Z" />
<meta property="article:modified_time" content="2026-09-29T13:10:00Z" />
</head><body><article>
<h1>Canadiens at Maple Leafs projected lineups</h1>
<p>Canadiens projected lineup</p>
<p>Chris Kreider -- Nick Suzuki -- Cole Caufield</p>
<p>Juraj Slafkovsky -- Alex Newhook -- Ivan Demidov</p>
<p>Mike Matheson -- Noah Dobson</p>
<p>Lane Hutson -- Alexandre Carrier</p>
<p>Scratched: Unknown Prospect</p>
<p>Maple Leafs projected lineup</p>
<p>Kirill Marchenko -- Auston Matthews -- Jack Roslovic</p>
<p>Gavin McKenna -- John Tavares -- William Nylander</p>
<p>Morgan Rielly -- Darren Raddysh</p>
<p>Jake McCabe -- Chris Tanev</p>
<p>Status report</p>
</article></body></html>
"""


def test_official_preview_url_from_game_identity_and_slate_date():
    url = preview_url({"away": "MTL", "home": "TOR"}, "2026-09-29")
    assert url == (
        "https://www.nhl.com/news/montreal-canadiens-toronto-maple-leafs"
        "-game-preview-september-29-2026")


def test_article_meta_timestamps_are_timezone_aware():
    article = Article()
    article.feed(SAMPLE)
    published, modified = publication_clock(article)
    assert published == utc("2026-09-29T12:20:00Z")
    assert modified == utc("2026-09-29T13:10:00Z")
    assert published.tzinfo == timezone.utc


def test_date_only_meta_not_certified():
    article = Article()
    article.feed('<meta property="article:published_time" content="2026-09-29" />')
    assert publication_clock(article) == (None, None)


def test_article_team_sections_do_not_bleed_into_each_other():
    article = Article()
    article.feed(SAMPLE)
    article._flush()
    away = read_lines(article.lines, "MTL")
    home = read_lines(article.lines, "TOR")
    assert ("Chris Kreider", "L1", "LW") in away
    assert ("Nick Suzuki", "L1", "C") in away
    assert ("Mike Matheson", "D1", "D") in away
    assert ("Kirill Marchenko", "L1", "LW") in home
    assert not any(name == "Auston Matthews" for name, _, _ in away)


def test_duplicate_player_names_are_not_arbitrarily_identified():
    roster = {"forwards": [
        {"id": 1, "firstName": {"default": "A."}, "lastName": {"default": "Same"}},
        {"id": 2, "firstName": {"default": "A."}, "lastName": {"default": "Same"}},
        {"id": 3, "firstName": {"default": "Cole"}, "lastName": {"default": "Caufield"}}],
        "defensemen": []}
    index = id_index(roster)
    assert normalize("A. Same") not in index
    assert index[normalize("Cole Caufield")] == "3"


def test_official_nhl_mixed_dash_2026_format_keeps_all_four_lines():
    """NHL's published lineups mix '--' and a Unicode en dash in one line.

    Treating the Unicode delimiter as part of a player's surname discards the
    entire fourth forward line and makes a legitimate 18-skater G2 projected
    pool appear incomplete. Distinct named defenders remain a separate cohort.
    """
    synthetic=[
       "Bruins projected lineup",
       "Alpha One -- Beta Two -- Gamma Three",
       "Delta Four -- Epsilon Five -- Zeta Six",
       "Eta Seven -- Theta Eight -- Iota Nine",
       "Kappa Ten – Lambda Eleven -- Mu Twelve",
       "Nu Thirteen -- Xi Fourteen",
       "Omicron Fifteen — Pi Sixteen",
       "Rho Seventeen -- Sigma Eighteen",
       "Goalie Name",
       "Second Goalie",
       "Scratched: Unavailable Person",
       "Red Wings projected lineup",
       "Other One -- Other Two -- Other Three",
    ]
    projected=read_lines(synthetic,"BOS")
    assert len(projected)==18
    assert ("Kappa Ten","L4","LW") in projected
    assert ("Lambda Eleven","L4","C") in projected
    assert ("Mu Twelve","L4","RW") in projected
    assert ("Omicron Fifteen","D2","D") in projected
    assert not any(player.startswith("Other") for player,_,_ in projected)
