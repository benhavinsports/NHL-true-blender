"""Regression: the watcher attaches confirmed evidence before inspecting changes."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from scripts import run_cycle


class WatchEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_attaches_confirmed_evidence_before_source_comparison(self):
        con = MagicMock()
        slate = {"games": [{"id": "2026020501", "away": "BOS", "home": "NJD",
                            "startUTC": "2026-11-19T01:00:00Z", "gameState": "FUT"}]}
        with (patch.object(run_cycle, "open_db", return_value=con),
              patch.object(run_cycle, "NHLClient") as client,
              patch.object(run_cycle, "official_slate", new_callable=AsyncMock,
                           return_value=slate),
              patch.object(run_cycle, "collect_secondary", new_callable=AsyncMock) as secondary,
              patch.object(run_cycle, "fetch_and_ingest_lineups", new_callable=AsyncMock,
                           return_value={"status": "DATED_SOURCE_PARSED"}) as lineups,
              patch.object(run_cycle, "attach") as attach,
              patch.object(run_cycle, "collect_watch", new_callable=AsyncMock,
                           return_value={"verifiedMaterialChanges": 1}) as compare,
              patch.object(run_cycle, "_write")):
            client.return_value.close = AsyncMock()
            result = await run_cycle.execute_cycle("watch", "2026-11-18")
        client.return_value.close.assert_awaited_once()
        secondary.assert_awaited_once_with(con, slate, "2026-11-18", "CONFIRMED")
        lineups.assert_awaited_once_with(con, slate, "2026-11-18", "CONFIRMED")
        attach.assert_called_once_with(con, slate, "2026-11-18", "CONFIRMED")
        compare.assert_awaited_once_with(None, con, "2026-11-18", slate)
        self.assertEqual(result["verifiedMaterialChanges"], 1)
        con.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
