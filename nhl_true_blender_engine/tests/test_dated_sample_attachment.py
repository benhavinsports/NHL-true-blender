"""Reproduce lossy archived summaries erasing corrected official samples."""
from copy import deepcopy
import pytest
from nhl_true_blender_engine.enrichment import attach, ingest, _same_sample_loses_detail
from nhl_true_blender_engine.storage import open_db

DAY = '2026-11-17'
BOX = 'https://api-web.nhle.com/v1/gamecenter/2026020325/boxscore'
PBP = BOX.replace('boxscore', 'play-by-play')


@pytest.mark.parametrize('kind,field', [('PLAYER_PRESSURE', 'pressure'),
                                      ('PLAYER_GAME_LOG', 'gameLog')])
def test_identical_dated_sample_keeps_known_shots_including_zero(tmp_path, kind, field):
    con = open_db(str(tmp_path / 'samples.sqlite'))
    good = {'appearances': [
        {'gameId': 'g1', 'date': '2026-11-14', 'shotsOnGoal': 3, 'goals': 1, 'sourceUrl': BOX},
        {'gameId': 'g2', 'date': '2026-11-12', 'shotsOnGoal': 0, 'goals': 0, 'sourceUrl': BOX}],
        'recentAppearanceShots': [3, 0]}
    lossy = deepcopy(good)
    for row in lossy['appearances']:
        row['shotsOnGoal'] = None
    lossy['recentAppearanceShots'] = [None, None]
    for i, payload in enumerate((good, lossy)):
        ingest(con, {'evidence_id': str(i), 'slate_date': DAY, 'stage': 'PROJECTED',
                     'game_id': 'today', 'player_id': '7', 'kind': kind,
                     'source_url': BOX, 'observed_at': f'2026-11-17T1{i}:00:00Z',
                     'payload': payload})
    snapshot = {'games': [{'id': 'today', 'away': 'A', 'home': 'B',
                          'goalies': {}, 'rosters': {'A': {'data': {'players': [{'id': '7'}]}}}}]}
    attach(con, snapshot, DAY, 'PROJECTED')
    data = snapshot['games'][0]['rosters']['A']['data']['players'][0][field]['data']
    assert [r['shotsOnGoal'] for r in data['appearances']] == [3, 0]
    assert data['sameSampleSummarySources'][0]['evidenceId'] == '1'
    # A concrete correction or a different window must not be discarded.
    changed = deepcopy(lossy)
    changed['appearances'][0]['shotsOnGoal'] = 4
    assert not _same_sample_loses_detail(kind, good, changed)
    changed = deepcopy(lossy)
    changed['appearances'][0]['gameId'] = 'different-game'
    assert not _same_sample_loses_detail(kind, good, changed)
    con.close()


def test_same_origin_summary_cannot_erase_dated_reconciliation_metadata():
    old = {'sourceType': 'OFFICIAL_NHL_DATED_PBP_SHOOTER_ORIGIN',
           'scope': 'RECENT_PRE_SLATE_TARGET_CLUB_GAMES_ONLY',
           'sampleGameIds': ['g1', 'zero-shot-g2'],
           'sampleCoverageComplete': False,  # Never upgraded by preservation.
           'zoneCounts': {'Low Slot': {'shotsOnGoal': 3, 'ownedGoals': 1,
               'sourceUrls': [PBP], 'byGame': [{'gameId': 'g1', 'date': '2026-11-14',
                   'shotsOnGoal': 3, 'ownedGoals': 1, 'sourceUrls': [PBP]}]}}}
    summary = {'sourceType': old['sourceType'], 'scope': old['scope'],
               'zoneCounts': {'Low Slot': {'shotsOnGoal': 3, 'ownedGoals': 1,
                   'sourceUrls': [PBP], 'gameIds': ['g1']}}}
    assert _same_sample_loses_detail('PLAYER_RECENT_ORIGIN', old, summary)
    assert old['sampleCoverageComplete'] is False
    for key, value in [('shotsOnGoal', 4), ('gameIds', ['different-game']),
                       ('sourceUrls', ['https://different-source.example/pbp'])]:
        changed = deepcopy(summary)
        changed['zoneCounts']['Low Slot'][key] = value
        assert not _same_sample_loses_detail('PLAYER_RECENT_ORIGIN', old, changed)
