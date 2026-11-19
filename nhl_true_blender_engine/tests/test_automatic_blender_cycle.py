"""Regression tests for the automated NHL slate phase and grade catch-up."""
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.automatic_blender_cycle import (
    choose_mode, pending_recent_grades, bootstrap_projected_before_confirmed,
    execute_commands, _record_grade_attempt)

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

    def test_confirmed_run_bootstraps_projected_only_before_all_puck_drops(self):
        games=[{"id":1,"startTimeUTC":"2026-11-19T23:00:00Z"},
               {"id":2,"startTimeUTC":"2026-11-20T01:00:00Z"},
               {"id":3,"startTimeUTC":"2026-11-20T03:00:00Z"}]
        with tempfile.TemporaryDirectory() as root, patch(
                "scripts.automatic_blender_cycle.subprocess.run") as run:
            executed=bootstrap_projected_before_confirmed(
                "2026-11-19",games,datetime(2026,11,19,17,0,tzinfo=ET),
                root=root)
            self.assertTrue(executed)
            run.assert_called_once_with(
                ["python","run_true_blender.py","--date","2026-11-19",
                 "--mode","projected"],check=True)
            run.reset_mock()
            self.assertFalse(bootstrap_projected_before_confirmed(
                "2026-11-19",games,datetime(2026,11,19,19,0,tzinfo=ET),
                root=root))
            run.assert_not_called()

    def test_existing_authoritative_card_is_never_bootstrapped_again(self):
        games=[{"id":1,"startTimeUTC":"2026-11-19T23:00:00Z"}]
        with tempfile.TemporaryDirectory() as root:
            con=sqlite3.connect(str(Path(root)/"true_blender.sqlite"))
            con.execute("CREATE TABLE cards (slate_date TEXT PRIMARY KEY)")
            con.execute("INSERT INTO cards VALUES (?)",("2026-11-19",))
            con.commit();con.close()
            with patch("scripts.automatic_blender_cycle.subprocess.run") as run:
                self.assertFalse(bootstrap_projected_before_confirmed(
                    "2026-11-19",games,datetime(2026,11,19,12,tzinfo=ET),
                    root=root))
                run.assert_not_called()

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

    def test_grade_failure_preserves_new_live_research_for_persistence(self):
        from subprocess import CompletedProcess
        import json
        with tempfile.TemporaryDirectory() as root:
            con=sqlite3.connect(str(Path(root)/"true_blender.sqlite"))
            con.execute("CREATE TABLE cards(slate_date TEXT, grade TEXT)")
            con.execute("INSERT INTO cards VALUES ('2026-11-18',NULL)")
            con.commit();con.close()
            # Isolate GITHUB_ENV from the real Actions job running pytest.
            with patch.dict("os.environ",
                            {"GITHUB_ENV": str(Path(root) / "github_env")}):
                with patch("scripts.automatic_blender_cycle.subprocess.run",
                           side_effect=[CompletedProcess([],0),
                                        CompletedProcess([],1)]) as run:
                    # Does not raise after the successful G0-G18 pipeline.
                    execute_commands("2026-11-19","projected",root=root)
                    self.assertEqual(run.call_count,2)
            self.assertIn("BLENDER_GRADE_RETRY_FAILURES=2026-11-18:1",
                          (Path(root)/"github_env").read_text())
            journal=json.loads((Path(root)/"grade_retry_journal.json").read_text())
            self.assertEqual(journal["attempts"]["2026-11-18"],1)
            self.assertEqual(journal["lastResults"]["2026-11-18"]["returnCode"],1)

    def test_grade_retry_round_robin_after_failed_old_receipts(self):
        with tempfile.TemporaryDirectory() as root:
            con=sqlite3.connect(str(Path(root)/"true_blender.sqlite"))
            con.execute("CREATE TABLE cards(slate_date TEXT, grade TEXT)")
            con.executemany("INSERT INTO cards VALUES (?,NULL)",
                            [("2026-10-10",),("2026-10-11",),("2026-10-12",)])
            con.commit();con.close()
            self.assertEqual(pending_recent_grades(root,"2026-11-19"),
                             ["2026-10-10","2026-10-11"])
            _record_grade_attempt(root,"2026-10-10",1)
            _record_grade_attempt(root,"2026-10-11",1)
            self.assertEqual(pending_recent_grades(root,"2026-11-19")[0],
                             "2026-10-12")

    def test_pregame_backlog_never_grades_current_slate(self):
        from subprocess import CompletedProcess
        with tempfile.TemporaryDirectory() as root:
            con=sqlite3.connect(str(Path(root)/"true_blender.sqlite"))
            con.execute("CREATE TABLE cards(slate_date TEXT, grade TEXT)")
            con.execute("INSERT INTO cards VALUES ('2026-11-19',NULL)")
            con.commit();con.close()
            with patch("scripts.automatic_blender_cycle.subprocess.run",
                       return_value=CompletedProcess([],0)) as run:
                execute_commands("2026-11-19","projected",root=root)
                run.assert_called_once_with(
                    ["python","run_true_blender.py","--date","2026-11-19",
                     "--mode","projected"],check=True)

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
