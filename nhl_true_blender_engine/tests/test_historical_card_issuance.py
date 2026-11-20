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


def test_historical_clock_is_used_for_card_and_version_timestamps(tmp_path):
    slate = '2026-10-07'
    cutoff = datetime(2026, 10, 7, 22, 45, tzinfo=timezone.utc)
    legs = [dict(gameId=str(i), playerId=str(8400000 + i), player=f'Fixture Player {i}',
                 path='PRIMARY', startUTC='2026-10-07T23:00:00Z', gameState='FUT',
                 sourceIds=['https://example.com/test-fixture']) for i in range(1, 4)]
    db = storage.open_db(str(tmp_path / 'historical-clock.sqlite'))
    try:
        card = storage.save_card(db, slate, 'PROJECTED', legs, games_count=3, now=cutoff)
        expected = cutoff.astimezone(storage.ET).isoformat(timespec='microseconds')
        assert card['first_issued_at'] == expected
        assert card['updated_at'] == expected
        version = db.execute('SELECT created_at FROM card_versions WHERE slate_date=?', (slate,)).fetchone()
        assert version['created_at'] == expected
    finally:
        db.close()


def test_persistence_clock_rejects_naive_datetime():
    with pytest.raises(ValueError, match='timezone-aware'):
        storage.stamp(datetime(2026, 10, 7, 22, 45))


def test_same_stage_goalie_source_refresh_is_saved_and_frozen_per_game(tmp_path):
    import json
    from copy import deepcopy
    slate='2026-11-19'
    before=datetime(2026,11,19,23,45,tzinfo=timezone.utc)
    after=datetime(2026,11,20,0,15,tzinfo=timezone.utc)
    legs=[dict(gameId=str(i),playerId=str(i+100),player=f'Player {i}',path='PRIMARY',
        startUTC=f'2026-11-20T0{i-1}:00:00Z',gameState='FUT',
        opposingGoalieId='old',sourceIds=['https://www.nhl.com/preview']) for i in (1,2,3)]
    con=storage.open_db(str(tmp_path/'source-refresh.sqlite'))
    try:
        first=storage.save_card(con,slate,'MIXED',legs,3,now=before)
        changed=deepcopy(legs);changed[0]['opposingGoalieId']='new'
        updated=storage.save_card(con,slate,'MIXED',changed,3,now=before)
        assert updated['fingerprint']==first['fingerprint']
        assert updated['revision']==2 and updated['initial_legs']==legs
        assert updated['current_legs']==changed
        rationale=json.loads(con.execute('SELECT rationale FROM card_versions WHERE revision=2').fetchone()[0])
        assert rationale['type']=='SAME_RECIPIENT_SOURCE_REFRESH'
        assert storage.save_card(con,slate,'MIXED',changed,3,now=after)['revision']==2
        frozen=deepcopy(changed);frozen[0]['opposingGoalieId']='too-late'
        with pytest.raises(ValueError,match='frozen leg'):
            storage.save_card(con,slate,'MIXED',frozen,3,now=after)
        future=deepcopy(changed);future[1]['opposingGoalieId']='new-later-game'
        result=storage.save_card(con,slate,'MIXED',future,3,now=after)
        assert result['revision']==3 and result['current_legs'][0]==changed[0]
        assert con.execute('SELECT COUNT(*) FROM cards').fetchone()[0]==1
    finally:
        con.close()
