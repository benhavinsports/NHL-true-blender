"""Edgehalla deployments are only accepted when dated and officially ID-joined."""
import unittest
from nhl_true_blender_engine.edgehalla_deployment import (
    source_asof, roster_identity, parsed_assignments,
)

ROSTER = [
    {"id":"1","name":"Alex Turcotte","jersey":15},
    {"id":"2","name":"Alex Laferriere","jersey":14},
    {"id":"3","name":"Adrian Kempe","jersey":9},
    {"id":"4","name":"Drew Doughty","jersey":8},
    {"id":"5","name":"Joel Edmundson","jersey":3},
    {"id":"6","name":"Kevin Fiala","jersey":22},
]
HTML = """<html><body>
<h1>Kings Line Combinations Today</h1>
<p>Updated Nov 19, 6:31 AM ET · through games of Nov 17</p>
<p>Projected for the next game, from their prior lineup.</p>
<h3>Forward lines (5v5)</h3><h4>L1</h4>
<ul><li>15 <a href="/nhl/players/alex-turcotte">Turcotte</a></li>
<li>14 <a href="/nhl/players/alex-laferriere">Laferriere</a></li>
<li>9 <a href="/nhl/players/adrian-kempe">Kempe</a></li></ul>
<h3>Defense pairs (5v5)</h3><h4>D1</h4>
<ul><li>8 <a href="/nhl/players/drew-doughty">Doughty</a></li>
<li>3 <a href="/nhl/players/joel-edmundson">Edmundson</a></li></ul>
<h3>Power-play units</h3><h4>PP1</h4>
<ul><li>15 <a href="/nhl/players/alex-turcotte">Turcotte</a></li>
<li>14 <a href="/nhl/players/alex-laferriere">Laferriere</a></li>
<li>9 <a href="/nhl/players/adrian-kempe">Kempe</a></li>
<li>8 <a href="/nhl/players/drew-doughty">Doughty</a></li>
<li>22 <a href="/nhl/players/kevin-fiala">Fiala</a></li></ul>
</body></html>"""


class EdgehallaG6Tests(unittest.TestCase):
    def test_current_dated_projection(self):
        self.assertEqual(source_asof(HTML,"2026-11-19")["sourceUpdateDay"],
                         "2026-11-19")

    def test_previous_day_fails(self):
        self.assertIsNone(source_asof(HTML,"2026-11-18"))

    def test_dated_narrative_alone_does_not_create_units(self):
        html = HTML.split("<h3>Forward lines")[0]
        self.assertFalse(parsed_assignments(html, ROSTER))

    def test_all_skater_ids_are_roster_verified(self):
        rows=parsed_assignments(HTML, ROSTER)
        self.assertEqual(rows["1"], {"EV":"F1", "PP":1})
        self.assertEqual(rows["4"], {"EV":"D1"})
        self.assertNotIn("6", rows)

    def test_wrong_shirt_number_is_not_matching_player(self):
        self.assertIsNone(roster_identity("Kempe","8",ROSTER))

    def test_partial_line_never_promoted(self):
        damaged=HTML.replace('<li>9 <a href="/nhl/players/adrian-kempe">Kempe</a></li>', '')
        self.assertNotIn("1", parsed_assignments(damaged, ROSTER))

if __name__ == "__main__":
    unittest.main()
