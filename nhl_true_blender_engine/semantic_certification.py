"""Independent substantive gate audit. A PASS label or URL alone is not proof.

Only explicit, source-linked observations satisfy positive requirements.
Neutral WHO/market checks remain neutral; no labels or weights are forced.
This module does not alter picks, persisted historical cards, or source data.
"""
from __future__ import annotations

PROVENANCE_REQUIRED = frozenset((
    'G0','G1','G2','G3','G4','G5','G6','G7','G9','G10',
    'G10.5','G11','G12','G15','G16','G17','G18'))

def audit_gate(gate, evidence, source_ids, stage):
    """Return independent reasons the alleged PASS is not certified."""
    e=evidence if isinstance(evidence,dict) else {}
    sources=[x for x in (source_ids or []) if isinstance(x,str) and x.startswith('https://')]
    gaps=[]
    def need(ok,reason):
        if not ok: gaps.append(reason)
    if gate in PROVENANCE_REQUIRED:
        need(bool(sources),'NO_SOURCE_ATTRIBUTION')
    if gate=='G0':
        need(e.get('directionSelectedBeforeSkaters') is True,'G0_DIRECTION_NOT_PROVED')
        need(bool(e.get('targetGoalie')) and bool(e.get('weakZones')),'G0_GOALIE_WEAKNESS_NOT_PROVED')
        need(e.get('selectedAttacker')==e.get('attacker'),'G0_ATTACK_SIDE_MISMATCH')
        need(e.get('branchStatus') in ('PROJECTED','EXPECTED','CONFIRMED'),'G0_GOALIE_STATUS_UNKNOWN')
    elif gate=='G1':
        context=e.get('venueRestTravel') or {}
        need(e.get('venueReviewed') is True and
             bool(context.get('venueHome') or context.get('venue')),'G1_VENUE_NOT_REVIEWED')
        need(e.get('bothTeamRestReviewed') is True and (
             (type(context.get('homeRestDays')) is int and
              type(context.get('awayRestDays')) is int) or
             bool(context.get('rest'))),'G1_REST_NOT_REVIEWED')
        need(e.get('travelUnobservedNotInvented') is True or
             type(context.get('travelMiles')) in (float,int),'G1_TRAVEL_EVIDENCE_UNCLEAR')
    elif gate=='G2':
        need(e.get('candidateOnOfficialRoster') is True,'G2_ROSTER_MEMBERSHIP_NOT_PROVED')
        need(e.get('availability') in ('DRESSED','CONFIRMED','PROJECTED_ACTIVE','UNVERIFIED'),
             'G2_STATUS_INELIGIBLE')
        if stage=='CONFIRMED':
            need(e.get('confirmedDressed') is True,'G2_DRESSED_STATUS_NOT_CONFIRMED')
    elif gate=='G3':
        need(e.get('opposingGoalieBranchReviewed') is True,'G3_GOALIE_BRANCH_NOT_REVIEWED')
        need(bool(e.get('goalieSample')) and bool(e.get('goalieWeakZones')) and
             bool(e.get('counterevidence')),'G3_WEAKNESS_AND_COUNTEREVIDENCE_INCOMPLETE')
    elif gate=='G4':
        own=e.get('ownRelease') or {}
        need(bool(e.get('archetype')) and bool(own.get('zone')),'G4_OWN_RELEASE_MISSING')
    elif gate=='G5':
        need(bool(e.get('shooterZone')) and
             e.get('shooterZone') in (e.get('weakZones') or {}),
             'G5_OWN_RELEASE_NOT_IN_GOALIE_WEAK_AREA')
    elif gate=='G6':
        d=e.get('deployment') or {}
        need(bool(d.get('EV')) and d.get('status') in ('PROJECTED','CONFIRMED'),
             'G6_DEPLOYMENT_NOT_PROVED')
        if stage=='CONFIRMED':
            need(d.get('status')=='CONFIRMED','G6_PROJECTED_DEPLOYMENT_NOT_CONFIRMED')
    elif gate=='G7':
        need(bool(e.get('eventLogReconciled')),'G7_GAME_LOG_NOT_RECONCILED')
    elif gate=='G8':
        need(e.get('neverRankingShortcut') is True and
             ('neutralWhenAbsent' in e),'G8_NEUTRAL_REVIEW_NOT_RECORDED')
    elif gate=='G9':
        need(bool(e.get('shooterZone')) and
             e.get('shooterZone') in (e.get('greenTarget') or []) and
             e.get('shooterZone') not in (e.get('redAvoid') or []),
             'G9_OPPONENT_DEFENSE_ROUTE_NOT_PROVED')
        need(e.get('coverageSourceType')=='OFFICIAL_HISTORICAL_NHL_PLAY_BY_PLAY' and
             e.get('coverageComparison')==
             'RECENT_OPPONENT_SHOT_ATTEMPT_ORIGIN_RATE_PER_GAME_VS_OTHER_TEAM_MEDIAN',
             'G9_LEGACY_OR_UNVERIFIED_COVERAGE_METHOD')
        z=e.get('zoneConcessionEvidence') or {}
        need(type(z.get('attemptsAgainst')) is int and
             z.get('attemptsAgainst',0)>=16 and
             type(z.get('gameCount')) is int and z.get('gameCount',0)>=6 and
             type(z.get('peerTeamsCompared')) is int and
             z.get('peerTeamsCompared',0)>=6 and
             type(z.get('attemptsPerGame')) in (int,float) and
             type(z.get('peerMedianAttemptsPerGame')) in (int,float) and
             z.get('attemptsPerGame',0)>z.get('peerMedianAttemptsPerGame',0),
             'G9_POSITIVE_PER_GAME_CONCESSION_PROOF_MISSING')
        need(e.get('lowShotVolumeNotStrengthEvidence') is True,
             'G9_LOW_VOLUME_MUST_NOT_BE_CALLED_DEFENSIVE_STRENGTH')
    elif gate=='G10':
        need(e.get('historicalDirectGoalRecipientVerified') is True and
             e.get('futureNotAssistOrFeederProven') is False,
             'G10_HISTORICAL_GOAL_CREDIT_NOT_SEPARATED')
    elif gate=='G10.5':
        rows=e.get('comparisonRows')
        need(e.get('allAlternativesScanned') is True and isinstance(rows,list) and
             all(r.get('status') in ('DEFEATED','DIFFERENT_TARGET_LANE',
                   'SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE') for r in rows),
             'G10_5_UNRESOLVED_DIRECT_RIVAL')
    elif gate=='G11':
        need(e.get('recentOwnAttempts') is not None,'G11_RECENT_SHOTS_NOT_PROVED')
    elif gate=='G12':
        own=e.get('ownership') or {}
        need(e.get('officialGoalsReconciled') is True and
             own.get('creditedGoalsVerified') is True,'G12_GOAL_MAPPING_NOT_RECONCILED')
    elif gate=='G13':
        need(e.get('qualitativeNameDateReview') is True and bool(e.get('name')) and
             bool(e.get('date')),'G13_QUALITATIVE_REVIEW_MISSING')
    elif gate=='G14':
        need(e.get('whoRouteReviewed') is True and e.get('noForcedWho') is True,
             'G14_WHO_ROUTE_NOT_CHECKED')
        need(e.get('unsupportedWhoEvidence') is False and
             (e.get('whoAnomalyPhysicallySupported') is True or
              e.get('neutralNoWhoAnomaly') is True),
             'G14_WHO_ANOMALY_UNRESOLVED')
    elif gate=='G15':
        need(e.get('independentHistoricalGoalFinishingEvidence') is True and
             e.get('separateOfficialShotOriginSource') is True and
             type(e.get('officialOwnedGoalsInMatchedOrigin')) is int and
             e.get('officialOwnedGoalsInMatchedOrigin')>0,
             'G15_FINISHER_PROOF_NOT_INDEPENDENT')
        need(len(sources)>=2,'G15_MISSING_SEPARATE_GOAL_CREDIT_AND_RELEASE_SOURCES')
    elif gate=='G16':
        rows=e.get('challengerRows')
        need(isinstance(rows,list) and e.get('includesDepthAndDefense') is True
             and e.get('everyOtherActiveTeammate')==len(rows) and
             all(r.get('status') in ('DEFEATED','DIFFERENT_TARGET_LANE',
                 'SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE') for r in rows),
             'G16_RIVAL_COMPETITION_NOT_RESOLVED')
    elif gate=='G17':
        c=e.get('counterevidence') or {}
        need(isinstance(c,dict) and c.get('unresolved') is False and
             bool(c.get('goalieStrengthReview')) and
             bool(c.get('lineupDisagreementReview')) and
             bool(c.get('strongestRivalReview')),
             'G17_STRUCTURED_CONTRADICTION_REVIEW_NOT_RESOLVED')
        if isinstance(c,dict) and c.get('sourceType')=='DERIVED_CROSS_SOURCE_G17':
            need(e.get('sourceDerivedReviewResolved') is True,
                 'G17_DERIVED_CONFLICT_NOT_RESOLVED')
            # G17 is a contradiction REVIEW, not a certificate of
            # anatomical glove/blocker/five-hole vulnerability. The actual
            # official NHL EDGE sources measure RINK SHOT ORIGIN. Requiring
            # anatomicalWeaknessCertified=True made EVERY derived G17 fail
            # permanently, even after a fully sourced, resolved comparison.
            # Preserve the explicit non-anatomical scope, and certify only a
            # genuinely matched/contradiction-free shot-origin review.
            goalie_review=c.get('goalieStrengthReview') or {}
            need(c.get('anatomicalWeaknessCertified') is False and
                 c.get('scope')=='observed shot origins, NOT anatomical goal-mouth coordinates' and
                 goalie_review.get('sourceScope')=='GOALIE_SHOT_ORIGIN_VS_SHOOTER_OWN_AREA',
                 'G17_RINK_ORIGIN_SCOPE_MISREPRESENTED')
            need(type(goalie_review.get('matchedWeakAreas')) is int and
                 goalie_review['matchedWeakAreas']>0 and
                 goalie_review.get('strongerAreaContradiction') is False,
                 'G17_OBSERVED_GOALIE_STRENGTH_CONTRADICTION_NOT_CLEARED')
            if stage=='CONFIRMED':
                need((c.get('lineupDisagreementReview') or {}).get('isTrulyConfirmed') is True,
                     'G17_LINEUP_DISAGREEMENT_NOT_CONFIRMED')
    elif gate=='G18':
        p=e.get('pathClassificationEvidence') or {}
        need(e.get('candidateEligibleForCrossGameFinal') is True and
             p.get('path') in ('PRIMARY','TRANSFER','WHO') and
             p.get('selectionIndependentOfLabel') is True,
             'G18_SOURCE_PATH_NOT_ADJUDICATED')
    elif gate.startswith('Step'):
        need(e.get('independentOverlayEvaluation') is True and
             e.get('checkedBeforeG18') is True and
             e.get('masterGateVerdictCopied') is False,
             'OVERLAY_NOT_INDEPENDENTLY_REVIEWED')
        if gate=='Step0': need(bool(e.get('weakOrigins')) and bool(e.get('targetGoalie')),
                               'STEP0_GOALIE_NOT_REVIEWED')
        elif gate=='Step1': need(e.get('candidateOnCurrentRoster') is True,
                                 'STEP1_ROSTER_NOT_REVIEWED')
        elif gate=='Step2': need(bool(e.get('venue')) and
                                 e.get('restSourceReviewed') is True,
                                 'STEP2_REST_NOT_PROVED')
        elif gate=='Step3': need(e.get('goalieWeakOriginMatch') is True and
                                 e.get('opponentDefenderAvoidZone') is not True,
                                 'STEP3_ATTACK_ZONE_NOT_PROVED')
        elif gate=='Step4': need(type(e.get('datedActualAppearances')) is int and
                                 e.get('datedActualAppearances')>0,
                                 'STEP4_APPEARANCES_NOT_PROVED')
        elif gate=='Step5': need(e.get('ownedArchetype') and
                                 e.get('creditedGoalsByOrigin') is not None,
                                 'STEP5_SHOOTER_MECHANISM_NOT_PROVED')
        elif gate=='Step6':
            need(bool(e.get('EV')) and e.get('sourceStatus') in ('PROJECTED','CONFIRMED'),
                 'STEP6_DEPLOYMENT_NOT_PROVED')
            if stage=='CONFIRMED':
                need(e.get('sourceStatus')=='CONFIRMED',
                     'STEP6_PROJECTED_NOT_CONFIRMED')
        elif gate=='Step7': need(bool(e.get('directOwnShotOrigin')),
                                 'STEP7_SHOOTER_ARCHETYPE_NOT_TAGGED')
        elif gate=='Step8': need(e.get('actualShiftByShiftObserved') is True and
                                 (e.get('officialShiftChartSourceCount') or 0)>0,
                                 'STEP8_SHIFT_EVIDENCE_NOT_PROVED')
        elif gate=='Step9': need(e.get('recentRouteContinuationMeasured') is True,
                                 'STEP9_RECENT_ROUTE_NOT_PROVED')
        elif gate=='Step10': need(bool(e.get('targetGoalieId')) and
                                  bool(e.get('ownRouteArea')),
                                  'STEP10_GOALIE_ROUTE_NOT_PROVED')
        elif gate=='Step10.5': need(e.get('everyActiveRivalReviewed') is True and
                                    e.get('noUnjustifiedTransfer') is False,
                                    'STEP10_5_RIVAL_DECISION_UNRESOLVED')
        elif gate=='Step11': need(e.get('WHOPathActuallySourceSupported') is True or
                                  e.get('neutralAbsenceOfWHOIsNotAnomaly') is True,
                                  'STEP11_WHO_REVIEW_NOT_RESOLVED')
        elif gate=='Step12': need(e.get('challengerCount')==e.get('comparisonRows') and
                                  not e.get('unresolvedChallengers'),
                                  'STEP12_RIVAL_REVIEW_INCOMPLETE')
        elif gate=='Step13': need(e.get('qualitativeReviewActuallyPerformed') is True,
                                  'STEP13_QUALITATIVE_REVIEW_NOT_PERFORMED')
        elif gate=='Step14': need(e.get('sourceContradictionsUnresolved') is False and
                                  bool(e.get('reviewedGoalieStrength')) and
                                  bool(e.get('reviewedLineupDisagreement')) and
                                  e.get('reviewedRivals') is True,
                                  'STEP14_CONTRADICTION_REVIEW_NOT_PROVED')
    return gaps
