"""Regression: a filled PASS matrix is not a source-certified gate execution."""
from nhl_true_blender_engine.semantic_certification import audit_gate

def test_g0_requires_prior_goalie_first_direction():
    evidence={'attacker':'DAL','targetGoalie':'99','weakZones':{'Low Slot':{}},
              'branchStatus':'CONFIRMED','selectedAttacker':'DAL'}
    assert 'G0_DIRECTION_NOT_PROVED' in audit_gate('G0',evidence,['https://nhl.com'],'CONFIRMED')
    evidence['directionSelectedBeforeSkaters']=True
    assert audit_gate('G0',evidence,['https://nhl.com'],'CONFIRMED')==[]

def test_g1_through_g3_never_pass_on_just_a_source_url():
    for gate in ('G1','G2','G3'):
        assert audit_gate(gate,{},['https://nhl.com'],'CONFIRMED')

def test_g14_needs_real_review_not_constant_true():
    assert 'G14_WHO_ROUTE_NOT_CHECKED' in audit_gate('G14',{},[],'PROJECTED')
    neutral={'whoRouteReviewed':True,'noForcedWho':True,
             'unsupportedWhoEvidence':False,'neutralNoWhoAnomaly':True}
    assert audit_gate('G14',neutral,['https://nhl.com'],'PROJECTED')==[]

def test_confirmed_phase_cannot_promote_projected_deployment():
    dep={'deployment':{'EV':'F1','status':'PROJECTED'}}
    assert 'G6_PROJECTED_DEPLOYMENT_NOT_CONFIRMED' in audit_gate(
        'G6',dep,['https://lineup.example'],'CONFIRMED')
    assert audit_gate('G6',dep,['https://lineup.example'],'PROJECTED')==[]

def test_g15_separate_own_goal_source_and_g17_real_rink_review_not_fake_anatomy():
    g15={'independentHistoricalGoalFinishingEvidence':True,
         'separateOfficialShotOriginSource':True,
         'officialOwnedGoalsInMatchedOrigin':2}
    assert 'G15_MISSING_SEPARATE_GOAL_CREDIT_AND_RELEASE_SOURCES' in audit_gate(
        'G15',g15,['https://nhl.com'],'CONFIRMED')
    g17={'sourceDerivedReviewResolved':True,
         'counterevidence':{'sourceType':'DERIVED_CROSS_SOURCE_G17',
            'scope':'observed shot origins, NOT anatomical goal-mouth coordinates',
            'goalieStrengthReview':{
                'matchedWeakAreas':1,
                'strongerAreaContradiction':False,
                'sourceScope':'GOALIE_SHOT_ORIGIN_VS_SHOOTER_OWN_AREA'},
            'lineupDisagreementReview':{
                'isTrulyConfirmed':False,'hasProjectedOrConfirmedRole':True},
            'strongestRivalReview':{'eachSameLaneDefeated':True},
            'unresolved':False,'anatomicalWeaknessCertified':False}}
    sources=['https://api-web.nhle.com/v1/edge/goalie-shot-location-detail/99/now']
    assert audit_gate('G17',g17,sources,'PROJECTED')==[]
    gaps=audit_gate('G17',g17,sources,'CONFIRMED')
    assert gaps==['G17_LINEUP_DISAGREEMENT_NOT_CONFIRMED']
    g17['counterevidence']['lineupDisagreementReview']['isTrulyConfirmed']=True
    assert audit_gate('G17',g17,sources,'CONFIRMED')==[]

def test_overlay_proves_own_checked_values_not_just_independent_flag():
    opaque={'independentOverlayEvaluation':True,'checkedBeforeG18':True,
            'masterGateVerdictCopied':False}
    assert 'STEP0_GOALIE_NOT_REVIEWED' in audit_gate('Step0',opaque,[],'CONFIRMED')


def test_g9_requires_positive_all_attempt_per_game_concession_not_legacy_green_label():
    evidence={
        "shooterZone":"L Point","greenTarget":["L Point"],"redAvoid":[],
        "coverageSourceType":"OFFICIAL_HISTORICAL_NHL_PLAY_BY_PLAY",
        "coverageComparison":"RECENT_OPPONENT_SHOT_ATTEMPT_ORIGIN_RATE_PER_GAME_VS_OTHER_TEAM_MEDIAN",
        "lowShotVolumeNotStrengthEvidence":True,
        "zoneConcessionEvidence":{
            "attemptsAgainst":24,"gameCount":8,"peerTeamsCompared":12,
            "attemptsPerGame":3.0,"peerMedianAttemptsPerGame":1.5}}
    sources=[f"https://api-web.nhle.com/v1/gamecenter/{i}/play-by-play"
             for i in range(8)]
    assert audit_gate("G9",evidence,sources,"PROJECTED")==[]
    legacy={**evidence,
        "coverageSourceType":None,
        "coverageComparison":"RECENT_OPPONENT_SHOT_ORIGIN_SHARES_AGAINST_PEER_MEDIAN"}
    gaps=audit_gate("G9",legacy,sources,"PROJECTED")
    assert "G9_LEGACY_OR_UNVERIFIED_COVERAGE_METHOD" in gaps
    insufficient={**evidence,"zoneConcessionEvidence":{
        **evidence["zoneConcessionEvidence"],"attemptsPerGame":1.0}}
    assert "G9_POSITIVE_PER_GAME_CONCESSION_PROOF_MISSING" in audit_gate(
        "G9",insufficient,sources,"PROJECTED")
