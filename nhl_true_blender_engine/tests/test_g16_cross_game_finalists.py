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
from nhl_true_blender_engine.gate_census import certify_gates
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


def matched_finalist(game, pid, goals, shots, goalie_percentile,
                    defense_ratio, goalie='EXPECTED', dep='PROJECTED',
                    zone='Low Slot'):
    """Independent SYNTHETIC opponent exposure, not historical-goal weights."""
    x=finalist(game,pid,goals,shots,goalie=goalie,dep=dep,zone=zone)
    x['attackTeam']='AWAY'
    x['targetGoalie']['sourceUrl']='https://api-web.nhle.com/v1/edge/goalie-shot-location-detail/'+str(game)+'/now'
    x['targetGoalie']['data']['weakZones']={
        zone:{'leagueSavePctgPercentile':goalie_percentile,
              'shotsAgainst':60,'goalsAgainst':12}}
    x['game']['coverage']={'AWAY':{
        'sourceUrl':'https://api-web.nhle.com/v1/gamecenter/'+str(game)+'/play-by-play',
        'observedAt':'2026-11-16T12:00:00Z',
        'data':{'zoneConcessions':{zone:{
            'onNetShotsPerGame':defense_ratio*8,
            'peerMedianOnNetShotsPerGame':8,
            'independentOnNetConcessionReview':True,
            'positiveConcessionBases':['ON_NET_SHOTS_AGAINST_PEER']}}}}}
    return x


def nov17_shape():
    # Former Nov 17 synthetic GOAL totals preserved, but new opponent-
    # specific exposure (not those goals) authorizes synthetic G16 separation.
    return [
        matched_finalist(335,'reinhart',6,30,.10,1.90),
        matched_finalist(341,'stutzle',6,14,.20,1.80),
        matched_finalist(340,'spurgeon',1,6,.85,1.05,zone='R Point'),
        matched_finalist(343,'smith',3,13,.30,1.70,zone='R Circle'),
    ]


def four_game_matchup_fixture():
    data=fixture(4)
    # Source-shaped independent goalie and opponent defensive exposure in
    # EVERY game. Without this, G16 must preserve a four-way deadlock.
    for i,game in enumerate(data['games']):
        away,home=game['away'],game['home']
        game['goalies'][home][0]['data']['weakZones']['slot'][
            'leagueSavePctgPercentile']=[.10,.20,.30,.85][i]
        attempts=[120,112,104,96][i]
        onnet=[88,80,72,64][i]
        game['coverage'][away]['data']['zoneConcessions']['slot'].update({
            'attemptsAgainst':attempts,
            'attemptsPerGame':attempts/8,
            'peerMedianAttemptsPerGame':10.0,
            'onNetShotsAgainst':onnet,
            'onNetShotsPerGame':onnet/8,
            'peerMedianOnNetShotsPerGame':7.0,
            'independentOnNetConcessionReview':True,
            'positiveConcessionBases':[
                'ATTEMPTS_AGAINST_PEER','ON_NET_SHOTS_AGAINST_PEER']})
    return data


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


def test_extra_qualified_game_does_not_reopen_a_revalidated_authoritative_card(tmp_path):
    from nhl_true_blender_engine.tests.test_engine import snapshot, DATE
    from nhl_true_blender_engine.storage import get_card
    con=open_db(str(tmp_path/'authority.sqlite'))
    try:
        original=execute(con,snapshot(3),DATE,'PROJECTED')['card']
        assert original is not None
        result=execute(con,snapshot(4),DATE,'CONFIRMED')
        assert result['card']['fingerprint']==original['fingerprint']
        assert result['g16FinalistCompetition']['comparisonSeparated'] is False
        assert result['g16FinalistCompetition']['decisionMode']=='REVALIDATE_AUTHORITATIVE_CARD'
        assert len(result['g16FinalistCompetition']['notSelectedExistingCardPlayerIds'])==1
        assert certify_gates(con,DATE,'CONFIRMED',4)['selectedCoreOnlyFullyCertified'] is True
        run={**result,'fingerprint':result['card']['fingerprint']}
        assert set(expected_core_ids(run))=={
            (x['gameId'],x['playerId']) for x in original['current_legs']}
        run['fingerprint']='not-the-authoritative-card'
        assert expected_core_ids(run) is None
        # Losing an actual source gate cannot be repaired by the card lock.
        slate=snapshot(4)
        slate['games'][0]['rosters']['T1A']['data']['players'][0].pop('deployment')
        failed=execute(con,slate,DATE,'CONFIRMED')
        assert failed['card'] is None
        assert get_card(con,DATE)['fingerprint']==original['fingerprint']
    finally:
        con.close()


def test_confirmed_goalie_status_is_a_g17_dimension_not_a_weight():
    # Same route evidence; only one finalist has an unconfirmed goalie.
    rows = [matched_finalist(1, 'a', 4, 20, .2, 1.4, goalie='CONFIRMED', dep='CONFIRMED'),
            matched_finalist(2, 'b', 4, 20, .2, 1.4, goalie='CONFIRMED', dep='CONFIRMED'),
            matched_finalist(3, 'c', 4, 20, .2, 1.4, goalie='CONFIRMED', dep='CONFIRMED'),
            matched_finalist(4, 'd', 4, 20, .2, 1.4, goalie='EXPECTED', dep='CONFIRMED')]
    retained, receipt = g16_cross_game_finalists(rows, 3)
    assert [x['candidate']['player']['id'] for x in retained] == ['a', 'b', 'c']
    # A stronger route with an unconfirmed goalie is NOT dominated.
    rows[3] = matched_finalist(4, 'd', 7, 40, .05, 2.0,
                             goalie='EXPECTED', dep='CONFIRMED')
    retained, receipt = g16_cross_game_finalists(rows, 3)
    assert len(retained) == 4 and receipt['separated'] is False


def test_core2_two_game_slate_never_runs_cross_game_exclusion():
    rows = [finalist(1, 'a', 6, 30), finalist(2, 'b', 1, 2)]
    core, errors = cross_game_winners(rows, 2)
    assert len(core) == 2 and errors == []


def test_g105_rival_dominating_route_is_elimination_not_missing_evidence():
    src = 'https://api-web.nhle.com/v1/edge/skater-shot-location-detail/%s/now'
    def rel(pid, goals, shots):
        return {'id': pid,
                'deployment': {'sourceUrl':src % pid+'/deployment','observedAt':'x',
                               'data':{'EV':'F2','status':'PROJECTED'}},
                'pressure': {'sourceUrl':src % pid+'/pressure','observedAt':'x',
                             'data':{'recentAppearanceShots':[1,2,3],
                                       'appearances':[{'date':'2026-11-11'},
                                                      {'date':'2026-11-12'},
                                                      {'date':'2026-11-13'}]}},
                'release': {'sourceUrl': src % pid, 'observedAt': 'x',
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
    data = four_game_matchup_fixture()
    # All four game recipients pass, but synthetic independent opponent-
    # specific G0/G9 exposure for the fourth is strictly weaker than three
    # other games. No historical goals select the final three.
    away = data['games'][3]['away']
    data['games'][3]['rosters'][away]['data']['players'][0] = player(130, 20, 2)
    con = open_db(str(tmp_path / 'four.sqlite'))
    try:
        result = execute(con, data, DATE, 'CONFIRMED')
        assert result['uniqueGameSurvivors'] == 4, {
            'errors':result.get('errors'),
            'missingByGate':result.get('missingByGate'),
            'pool':[(p.get('matchup'),p.get('status'),
                     p.get('firstNonPassGateCounts')) for p in
                    result.get('gameSurvivorPool',[])],
        }
        assert 'allG18QualifiedSurvivors' not in result
        survivors = result['preCoreQualifiedSurvivors']
        assert {x['playerId'] for x in survivors} == {'100', '110', '120', '130'}
        # G16 exclusion must not erase a source-backed game survivor.
        game_pool = next(x for x in result['gameSurvivorPool']
                         if (x.get('survivor') or {}).get('playerId') == '130')
        assert game_pool['status'] == 'SURVIVOR'
        assert game_pool['inCore'] is False
        assert game_pool['g16Decision'].startswith('EXCLUDED_')
        assert len(result['gameSurvivorPool']) == 4
        assert result['card'] is not None, result['errors']
        legs = result['card']['current_legs']
        assert {x['playerId'] for x in legs} == {'100', '110', '120'}
        g16 = result['g16FinalistCompetition']
        assert g16['excludedPlayerIds'] == ['130'] and g16['separated'] is True
        census = certify_gates(con, DATE, 'CONFIRMED', 4)
        funnel = census['selectionFunnel']
        assert funnel['qualifiedButNotChosen'] == 1
        assert funnel['lockedCoreRecipients'] == 3
        assert census['firstFailureClassificationCounts']['CROSS_GAME_NOT_SELECTED'] == 1
        # The G16-excluded 130 remains qualified at GAME level despite
        # not receiving G18 PASS; no new ranking or player replacement.
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
    data=four_game_matchup_fixture()
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
        assert {x['playerId'] for x in result['preCoreQualifiedSurvivors']} == (g18_pass | {'130'})
        assert 'allG18QualifiedSurvivors' not in result
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
