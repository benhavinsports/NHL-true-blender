"""G16 final challenger competition across per-game survivors.

Regression for the 2026-11-17 deadlock: four games each produced one fully
qualified recipient and G18 refused to issue any Core because it may not
rank. G16 must compare all meaningful surviving candidates using only the
original direct-route and contradiction evidence, with no weights.
"""
from nhl_true_blender_engine.engine import (
    g16_cross_game_finalists, cross_game_winners, challenger_proof,
    execute)
from nhl_true_blender_engine.core_identity import expected_core_ids
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_end_to_end_contract import (
    fixture, player, DATE)


def finalist(game, pid, goals, shots, goalie='EXPECTED', dep='PROJECTED', zone='Low Slot'):
    src = 'https://api-web.nhle.com/v1/edge/skater-shot-location-detail/%s/now' % pid
    return {
        'game': {'id': game},
        'targetGoalie': {'data': {'status': goalie, 'goalieId': 'G' + str(game)}},
        'candidate': {
            'player': {'id': pid, 'name': 'P' + str(pid),
                       'deployment': {'sourceUrl': src, 'observedAt': 'x',
                                      'data': {'EV': 'L1', 'status': dep}}},
            'release': {'zone': zone, 'ownedGoals': goals, 'attempts': shots},
        },
    }


def nov17_shape():
    # Same shape as the saved 2026-11-17 receipt (own lane goals / SOG).
    return [finalist(335, 'reinhart', 6, 30), finalist(341, 'stutzle', 6, 14),
            finalist(340, 'spurgeon', 1, 6, zone='R Point'),
            finalist(343, 'smith', 3, 13, zone='R Circle')]


def test_four_survivors_g16_excludes_only_fully_dominated_route():
    retained, receipt = g16_cross_game_finalists(nov17_shape(), 3)
    ids = [x['candidate']['player']['id'] for x in retained]
    assert ids == ['reinhart', 'stutzle', 'smith']
    assert receipt['excludedPlayerIds'] == ['spurgeon']
    spurgeon = next(x for x in receipt['finalists'] if x['playerId'] == 'spurgeon')
    assert sorted(spurgeon['dominatedBy']) == ['reinhart', 'smith', 'stutzle']
    assert receipt['separated'] is True and receipt['noWeightsSumsRatesOrTieBreaks']
    # G18 then only assembles the three retained survivors.
    core, errors = cross_game_winners(retained, 11)
    assert len(core) == 3 and errors == []


def test_unseparated_finalists_produce_no_core_and_no_tiebreak():
    # Two bottom finalists trade off goals vs shots: neither dominates the
    # other, and each is dominated by only two finalists. No Core.
    rows = [finalist(1, 'a', 6, 30), finalist(2, 'b', 6, 20),
            finalist(3, 'c', 3, 5), finalist(4, 'd', 1, 15)]
    retained, receipt = g16_cross_game_finalists(rows, 3)
    assert len(retained) == 4 and receipt['separated'] is False
    core, errors = cross_game_winners(retained, 11)
    assert core == [] and 'PRE_CORE_REVIEW' in errors[0]


def test_confirmed_goalie_status_is_a_g17_dimension_not_a_weight():
    # Same route evidence; only one finalist has an unconfirmed goalie.
    rows = [finalist(1, 'a', 4, 20, goalie='CONFIRMED', dep='CONFIRMED'),
            finalist(2, 'b', 4, 20, goalie='CONFIRMED', dep='CONFIRMED'),
            finalist(3, 'c', 4, 20, goalie='CONFIRMED', dep='CONFIRMED'),
            finalist(4, 'd', 4, 20, goalie='EXPECTED', dep='CONFIRMED')]
    retained, receipt = g16_cross_game_finalists(rows, 3)
    assert [x['candidate']['player']['id'] for x in retained] == ['a', 'b', 'c']
    # A stronger route with an unconfirmed goalie is NOT dominated.
    rows[3] = finalist(4, 'd', 7, 40, goalie='EXPECTED', dep='CONFIRMED')
    retained, receipt = g16_cross_game_finalists(rows, 3)
    assert len(retained) == 4 and receipt['separated'] is False


def test_core2_two_game_slate_never_runs_cross_game_exclusion():
    rows = [finalist(1, 'a', 6, 30), finalist(2, 'b', 1, 2)]
    core, errors = cross_game_winners(rows, 2)
    assert len(core) == 2 and errors == []


def test_g105_rival_dominating_route_is_elimination_not_missing_evidence():
    src = 'https://api-web.nhle.com/v1/edge/skater-shot-location-detail/%s/now'
    def rel(pid, goals, shots):
        return {'id': pid, 'release': {'sourceUrl': src % pid, 'observedAt': 'x',
                'data': {'archetype': 'wrist', 'zone': 'slot', 'attempts': shots,
                         'ownedGoals': goals,
                         'allRoutes': [{'zone': 'slot', 'sog': shots, 'ownedGoals': goals}]}}}
    weak, strong = rel('1', 1, 5), rel('2', 4, 20)
    ok, rows = challenger_proof(weak, [strong], {'slot': {}}, ['slot'])
    assert ok is False and rows[0]['status'] == 'RIVAL_DOMINATES'
    missing = {'id': '3'}
    ok, rows = challenger_proof(strong, [missing], {'slot': {}}, ['slot'])
    assert ok is False and rows[0]['status'] == 'NO_RELEASE_SOURCE'


def test_end_to_end_g105_loser_recorded_as_eliminated(tmp_path):
    con = open_db(str(tmp_path / 'g105.sqlite'))
    try:
        result = execute(con, fixture(), DATE, 'CONFIRMED')
        rows = con.execute("SELECT player_id, disposition FROM gates WHERE gate='G10.5'"
                           " AND player_id IN ('101','111','121')").fetchall()
        assert rows and all(r['disposition'] == 'ELIMINATED' for r in rows)
    finally:
        con.close()


def test_end_to_end_four_qualified_games_issue_one_g16_separated_core(tmp_path):
    data = fixture(4)
    # Game 3's strongest recipient still wins its own G10.5 (2G/20 vs 1G/10)
    # but every other game's recipient (3G/30) strictly dominates it.
    away = data['games'][3]['away']
    data['games'][3]['rosters'][away]['data']['players'][0] = player(130, 20, 2)
    con = open_db(str(tmp_path / 'four.sqlite'))
    try:
        result = execute(con, data, DATE, 'CONFIRMED')
        assert result['uniqueGameSurvivors'] == 4
        assert result['card'] is not None, result['errors']
        legs = result['card']['current_legs']
        assert {x['playerId'] for x in legs} == {'100', '110', '120'}
        g16 = result['g16FinalistCompetition']
        assert g16['excludedPlayerIds'] == ['130'] and g16['separated'] is True
        # Renaming the receipt must not change the four game survivors or
        # the three final G18 recipients after cross-game G16.
        pre_core = result['preCoreQualifiedSurvivors']
        assert len(pre_core) == 4
        assert {x['playerId'] for x in pre_core} == {'100', '110', '120', '130'}
        run = {'preCoreQualifiedSurvivors': result['preCoreQualifiedSurvivors'],
               'g16FinalistCompetition': g16}
        assert set(expected_core_ids(run)) == {(x['gameId'], x['playerId']) for x in legs}
        # Re-running never issues a second or different card.
        again = execute(con, data, DATE, 'CONFIRMED')
        assert again['card']['card_id'] == result['card']['card_id']
        assert again['card']['revision'] == 1
    finally:
        con.close()


def test_publication_rejects_tampered_g16_receipt():
    retained, receipt = g16_cross_game_finalists(nov17_shape(), 3)
    survivors = [{'gameId': x['gameId'], 'playerId': x['playerId']} for x in receipt['finalists']]
    run = {'preCoreQualifiedSurvivors': survivors, 'g16FinalistCompetition': receipt}
    assert len(expected_core_ids(run)) == 3
    # Dropping a survivor from the receipt, or claiming an exclusion without
    # a full Core of dominators, must not verify.
    bad = {**run, 'preCoreQualifiedSurvivors': survivors[:3]}
    assert expected_core_ids(bad) is None
    forged = {**receipt, 'finalists': [dict(f) for f in receipt['finalists']]}
    forged['finalists'][2]['dominatedBy'] = ['reinhart']
    assert expected_core_ids({**run, 'g16FinalistCompetition': forged}) is None
    unseparated = {**receipt, 'separated': False}
    assert expected_core_ids({**run, 'g16FinalistCompetition': unseparated}) is None


def test_g18_pass_is_only_final_core_after_cross_game_g16(tmp_path):
    """No player can pass G18 and then be thrown out by a later G16."""
    import json
    data=fixture(4)
    away=data['games'][3]['away']
    data['games'][3]['rosters'][away]['data']['players'][0]=player(130,20,2)
    con=open_db(str(tmp_path / 'only-final-g18.sqlite'))
    try:
        result=execute(con,data,DATE,'CONFIRMED')
        assert result['card'] is not None, result['errors']
        chosen={x['playerId'] for x in result['card']['current_legs']}
        rows=con.execute(
            "SELECT player_id,disposition,details FROM gates "
            "WHERE slate_date=? AND stage='CONFIRMED' AND gate='G18'",
            (DATE,)).fetchall()
        g18_pass={r['player_id'] for r in rows if r['disposition']=='PASS'}
        assert g18_pass==chosen=={'100','110','120'}
        # Final non-Core decisions are NOT absent source evidence at G18.
        # The older missingByGate count wrongly reported every non-Core
        # player as missing proof of the final Core assembly gate.
        non_core=[r for r in rows if r['disposition']=='NOT_EXECUTED']
        assert result['missingByGate'].get('G18',0)==0
        assert result['g18IntentionallyNotSelectedNotMissingSource']==len(non_core)
        rejected=next(r for r in rows if r['player_id']=='130')
        assert rejected['disposition']=='NOT_EXECUTED'
        evidence=json.loads(rejected['details'])
        assert evidence['evidence']['G18CoreSlotGrantedOnlyAfterG16'] is False
        g16=con.execute(
            "SELECT disposition,details FROM gates "
            "WHERE slate_date=? AND stage='CONFIRMED' AND gate='G16' "
            "AND player_id='130'",(DATE,)).fetchone()
        assert g16['disposition']=='ELIMINATED'
        receipt=json.loads(g16['details'])['evidence']
        assert receipt['crossGameFinalistCompetition']['decision'].startswith('EXCLUDED_')
        assert all(json.loads(r['details'])['evidence']['G18FinalAssemblyAfterFullG16']
                   for r in rows)
    finally:
        con.close()
