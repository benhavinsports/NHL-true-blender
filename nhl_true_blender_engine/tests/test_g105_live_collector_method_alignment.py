"""G10.5: the same G0 and G9 source population feeds recipient separation.

Use source-shaped synthetic fixtures only; neither these tests nor their
historical on-net-shot counts purport to predict a future scored goal.
"""
from nhl_true_blender_engine.engine import _tonight_route_comparison, challenger_proof
from nhl_true_blender_engine.tests.test_engine import skater


def peer_zones():
    return {
        'Low Slot':{
            'shotsAgainst':55,'goalsAgainst':13,
            'samplePeerSavePctgPercentile':.10,'peerGoaliesSampled':12,
            'samplePeerPopulationId':'stable-2026-11-20-pre-slate',
            'samplePeerPopulationStable':True,
        },
        'R Circle':{
            'shotsAgainst':51,'goalsAgainst':5,
            'samplePeerSavePctgPercentile':.75,'peerGoaliesSampled':12,
            'samplePeerPopulationId':'stable-2026-11-20-pre-slate',
            'samplePeerPopulationStable':True,
        },
    }


def coverage():
    return {'zoneConcessions':{
        'Low Slot':{
            'onNetShotsPerGame':10,'peerMedianOnNetShotsPerGame':8,
            'attemptsPerGame':18,'peerMedianAttemptsPerGame':12,
            'independentOnNetConcessionReview':True,
            'positiveConcessionBases':['ON_NET_SHOTS_AGAINST_PEER','ATTEMPTS_AGAINST_PEER']},
        'R Circle':{
            'onNetShotsPerGame':9,'peerMedianOnNetShotsPerGame':8,
            'attemptsPerGame':15,'peerMedianAttemptsPerGame':12,
            'independentOnNetConcessionReview':True,
            'positiveConcessionBases':['ON_NET_SHOTS_AGAINST_PEER','ATTEMPTS_AGAINST_PEER']},
    }}


def test_independently_source_qualified_pbp_peer_winner():
    evidence=_tonight_route_comparison('Low Slot','R Circle',peer_zones(),coverage())
    assert evidence['result']=='CANDIDATE'
    assert evidence['comparableGoaliePeerMethod']=='OFFICIAL_PBP_STABLE_PEERS:stable-2026-11-20-pre-slate'
    assert evidence['comparableDefenseConcessionMethod']=='G9_ON_NET_VS_PEERS'
    assert evidence['noHistoricalGoalsUsedForDecision'] is True


def test_g9_independent_attempts_only_scope_is_supported():
    d=coverage()
    for z in d['zoneConcessions'].values():
        z['onNetShotsPerGame']=7  # no source-positive on-net vulnerability
        z['positiveConcessionBases']=['ATTEMPTS_AGAINST_PEER']
    evidence=_tonight_route_comparison('Low Slot','R Circle',peer_zones(),d)
    assert evidence['result']=='CANDIDATE'
    assert evidence['comparableDefenseConcessionMethod']=='G9_ATTEMPTS_VS_PEERS'


def test_starter_dependent_or_mismatched_pbp_cohorts_never_assumed_comparable():
    goalies=peer_zones()
    goalies['R Circle']['samplePeerPopulationId']='different-slate'
    assert _tonight_route_comparison('Low Slot','R Circle',goalies,coverage()) is None
    goalies['R Circle']['samplePeerPopulationId']='stable-2026-11-20-pre-slate'
    goalies['R Circle']['samplePeerPopulationStable']=False
    assert _tonight_route_comparison('Low Slot','R Circle',goalies,coverage()) is None


def test_g10_5_recipient_uses_opponent_not_previous_goals_when_pbp_only():
    candidate=skater(8711,'Low Slot',12,1)
    challenger=skater(8712,'R Circle',30,8)
    first,rows=challenger_proof(candidate,[challenger],peer_zones(),
                                ['Low Slot','R Circle'],opponent_coverage=coverage())
    assert first is True
    assert rows[0]['status']=='DEFEATED'
    assert rows[0]['tonightMatchupComparison']['result']=='CANDIDATE'
    assert rows[0]['candidate']['ownedGoals']==1
    assert rows[0]['challenger']['ownedGoals']==8


def test_unshared_defense_methods_cannot_create_winner():
    d=coverage()
    d['zoneConcessions']['Low Slot']['positiveConcessionBases']=['ON_NET_SHOTS_AGAINST_PEER']
    d['zoneConcessions']['R Circle']['positiveConcessionBases']=['ATTEMPTS_AGAINST_PEER']
    assert _tonight_route_comparison('Low Slot','R Circle',peer_zones(),d) is None
