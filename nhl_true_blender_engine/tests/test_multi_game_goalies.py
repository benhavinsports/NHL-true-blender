"""Regression: each matchup's goalie section must survive preceding team injuries."""
from nhl_true_blender_engine.lineup_parser import parse_markdown

TEXT="""# Tonight in the NHL: line combinations and starting goalies (games dated 2026-11-15)
## Edmonton Oilers at Philadelphia Flyers
Starting goalies:
- Tristan Jarry (EDM), Unconfirmed, 2.60 GAA
- Dan Vladar (PHI), Confirmed, 3.24 GAA
### Philadelphia Flyers
Forward lines:
1. First Player – Second Player – Third Player
Injuries:
- Hurt Player (C, Injured Reserve)
## Calgary Flames at Anaheim Ducks
Starting goalies:
- Dustin Wolf (CGY), Unconfirmed, 3.58 GAA
- Lukas Dostal (ANA), Unconfirmed, 3.97 GAA
### Anaheim Ducks
Forward lines:
1. Fourth Player – Fifth Player – Sixth Player
Injuries:
- Another Injured Player (D, Injured Reserve)
## Florida Panthers at Dallas Stars
Starting goalies:
- Jacob Markstrom (FLA), Unconfirmed, 2.41 GAA
- Jake Oettinger (DAL), Unconfirmed, 2.17 GAA
"""

def test_parse_all_scheduled_game_goalie_reports_after_injuries():
    parsed=parse_markdown(TEXT)
    assert len(parsed["goalies"])==6
    assert [x["team"] for x in parsed["goalies"]]==["EDM","PHI","CGY","ANA","FLA","DAL"]
    assert parsed["goalies"][1]["status"]=="CONFIRMED"
    assert len(parsed["teams"]["Philadelphia Flyers"]["injuries"])==1
    assert len(parsed["teams"]["Anaheim Ducks"]["injuries"])==1
