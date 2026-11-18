from datetime import datetime, timezone

import pytest

from nhl_true_blender_engine import storage


def test_historical_cutoff_allows_first_issuance_but_live_clock_does_not(tmp_path, monkeypatch):
    slate = '2026-10-07'
    cutoff = datetime(2026, 10, 7, 22, 45, tzinfo=timezone.utc)
    legs = [dict(gameId=str(i), playerId=str(8400000 + i), player=f'Fixture Player {i}',
                 path='PRIMARY', startUTC='2026-10-07T23:00:00Z', gameState='FUT',
                 sourceIds=['https://example.com/test-fixture']) for i in range(1, 4)]

    class ReplayDayClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 11, 18, 10, 0, tzinfo=timezone.utc)
            return value.replace(tzinfo=None) if tz is None else value.astimezone(tz)

    monkeypatch.setattr(storage, 'datetime', ReplayDayClock)
    db = storage.open_db(str(tmp_path / 'replay.sqlite'))
    try:
        with pytest.raises(ValueError, match='already-started game'):
            storage.save_card(db, slate, 'PROJECTED', legs, games_count=3)
        assert storage.get_card(db, slate) is None
        card = storage.save_card(db, slate, 'PROJECTED', legs, games_count=3, now=cutoff)
        assert card['revision'] == 1
        assert card['initial_legs'] == card['current_legs'] == legs
        assert card['fingerprint'] == storage.fingerprint(legs)
        assert storage.get_card(db, slate) == card
    finally:
        db.close()
