"""Regression tests for the automated NHL slate phase and grade catch-up."""
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.automatic_blender_cycle import choose_mode, pending_recent_grades

ET = ZoneInfo("America/New_York")
GAMES = [
    {"id": 1, "startTimeUTC": "2026-11-18T18:00:00Z"},
    {"id": 2, "startTimeUTC": "2026-11-19T01:00:00Z"},
]


class AutomaticBlenderCycleTests(unittest.TestCase):
    def test_overnight_today_is_projected_not_yesterdays_grade(self):
        # The daily Card must begin researching the NEW Eastern slate after
        # midnight. Previously the 08:00 ET hard cutoff suppressed all
        # G0-G18 scouting on today's games for eight hours.
        today = [{"id": 10, "startTimeUTC": "2026-11-20T00:00:00Z"}]
        self.assertEqual(choose_mode(today,
                         datetime(2026, 11, 19, 1, 36, tzinfo=ET),
                         date="2026-11-19"), "projected")

    def test_early_projected(self):
        self.assertEqual(choose_mode(GAMES, datetime(2026, 11, 18, 9, 0, tzinfo=ET)),
                         "projected")

    def test_early_matinee_receives_confirmed_research(self):
        self.assertEqual(choose_mode(GAMES, datetime(2026, 11, 18, 11, 5, tzinfo=ET)),
                         "confirmed")

    def test_later_games_still_confirmed_after_seven_pm(self):
        self.assertEqual(choose_mode(GAMES, datetime(2026, 11, 18, 19, 20, tzinfo=ET)),
                         "confirmed")

    def test_postgame_not_prematurely_marked_final(self):
        self.assertEqual(choose_mode(GAMES, datetime(2026, 11, 18, 21, 0, tzinfo=ET)),
                         "grade")

    def test_prior_day_is_grade(self):
        self.assertEqual(choose_mode(GAMES, datetime(2026, 11, 19, 11, tzinfo=ET),
                                     date="2026-11-18"), "grade")

    def test_missing_start_does_not_silently_infer_schedule(self):
        with self.assertRaises(ValueError):
            choose_mode([{"id": 1}], datetime(2026, 11, 18, 15, tzinfo=ET))

    def test_season_old_frozen_card_is_not_abandoned(self):
        with tempfile.TemporaryDirectory() as dirname:
            con = sqlite3.connect(str(Path(dirname) / "true_blender.sqlite"))
            con.execute("CREATE TABLE cards(slate_date TEXT, grade TEXT)")
            con.executemany("INSERT INTO cards VALUES (?,?)", [
                ("2026-08-31", None), ("2026-09-29", None),
                ("2026-10-07", ""), ("2026-11-18", None)])
            con.commit()
            con.close()
            self.assertEqual(pending_recent_grades(dirname, "2026-11-18"),
                             ["2026-09-29", "2026-10-07"])

    def test_recent_ungraded_frozen_cards_are_retried_bounded(self):
        with tempfile.TemporaryDirectory() as dirname:
            con = sqlite3.connect(str(Path(dirname) / "true_blender.sqlite"))
            con.execute("CREATE TABLE cards(slate_date TEXT, grade TEXT)")
            con.executemany("INSERT INTO cards VALUES (?,?)", [
                ("2026-11-15", ""), ("2026-11-16", None),
                ("2026-11-17", "WIN"), ("2026-11-18", None)])
            con.commit()
            con.close()
            self.assertEqual(pending_recent_grades(dirname, "2026-11-18"),
                             ["2026-11-15", "2026-11-16"])


if __name__ == "__main__":
    unittest.main()
