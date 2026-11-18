from datetime import datetime, timezone

from scripts.ingest_dfo_goalie_evidence import official_game_start
from scripts.inventory_dfo_historical_goalies import _official_game_start


def test_dfo_ingestion_accepts_official_calendar_start_utc_alias():
    value = official_game_start({"startUTC": "2026-09-29T21:00:00Z"})
    assert value == datetime(2026, 9, 29, 21, 0, tzinfo=timezone.utc)


def test_dfo_ingestion_accepts_legacy_start_time_utc_alias():
    value = official_game_start({"startTimeUTC": "2026-09-29T21:00:00.000Z"})
    assert value == datetime(2026, 9, 29, 21, 0, tzinfo=timezone.utc)


def test_dfo_ingestion_rejects_missing_or_timezone_free_game_start():
    assert official_game_start({"gameId": "2026020001"}) is None
    assert official_game_start({"startUTC": "2026-09-29T21:00:00"}) is None

def test_dfo_inventory_uses_official_calendar_start_utc_alias():
    value = _official_game_start({"startUTC": "2026-09-29T21:00:00Z"})
    assert value == datetime(2026, 9, 29, 21, 0, tzinfo=timezone.utc)


def test_dfo_inventory_rejects_timezone_free_game_start():
    assert _official_game_start({"startUTC": "2026-09-29T21:00:00"}) is None
