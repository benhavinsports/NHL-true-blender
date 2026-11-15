import unittest
from nhl_true_blender_engine.lineup_parser import parse_markdown

class LineupParserTests(unittest.TestCase):
    def test_lineups_pp_and_goalie_status_are_separate(self):
        source = """# Tonight in the NHL: line combinations and starting goalies (games dated 2026-11-15)
## Edmonton Oilers at Philadelphia Flyers
Starting goalies:
- Devon Levi (EDM), Unconfirmed, 9-1-0
- Dan Vladar (PHI), Confirmed, 3-4-4
### Edmonton Oilers
Forward lines:
1. Vasily Podkolzin – Connor McDavid – Leon Draisaitl
Defense pairs:
1. Mattias Ekholm – Evan Bouchard
Power play 1: Zach Hyman – Connor McDavid – Leon Draisaitl – Evan Bouchard – Ryan Nugent-Hopkins
Injuries:
- Alec Regula (D, Injured Reserve)
"""
        parsed = parse_markdown(source)
        edm = parsed["teams"]["Edmonton Oilers"]
        self.assertEqual(edm["lines"][0][1], "Connor McDavid")
        self.assertEqual(len(edm["pp"]["1"]), 5)
        self.assertEqual(len(edm["injuries"]), 1)
        self.assertEqual(parsed["goalies"][0]["status"], "UNCONFIRMED")
        self.assertEqual(parsed["goalies"][1]["status"], "CONFIRMED")

if __name__ == "__main__":
    unittest.main()
