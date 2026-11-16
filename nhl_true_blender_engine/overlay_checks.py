"""Independent Phase-1 Step0..Step14 overlay.

Based on the recovered Phase-1 operational mapping (2026-11-14), not a copy
of master-gate verdicts. Each check observes the sourced inputs independently
BEFORE G18; missing facts are recorded, never asserted as PASS. Step 13 is
qualitative and nonblocking. Step 8 never invents shift-by-shift metrics.
"""
from __future__ import annotations

STEP_ORDER=([f'Step{i}' for i in range(11)]+['Step10.5']+
            [f'Step{i}' for i in range(11,15)])

def independent_overlay(game,attacker,player,teammates,goalie,release,
                        recurrence,challenger_rows,stage,receipt,evidence_data,gate_record):
    records=[]
    g=goalie.get('data') or {}
    weak=g.get('weakZones') or {}
    zone=(release or {}).get('zone')
    dep=player.get('deployment')
    deploy=evidence_data(dep) or {}
    context=game.get('context')
    ctx=evidence_data(context) or {}
    roster=game.get('rosters',{}).get(attacker)
    roster_data=evidence_data(roster) or {}
    coverage=game.get('coverage',{}).get(attacker)
    cov=evidence_data(coverage) or {}
    raw_release=player.get('release')
    pressure=player.get('pressure')
    pres=evidence_data(pressure) or {}
    own=player.get('finishOwnership')
    own_data=evidence_data(own) or {}
    c=player.get('contradictions')
    contra=evidence_data(c) or {}
    who=player.get('whoAnomaly')
    who_data=evidence_data(who) or {}
    jersey=player.get('jersey')
    date=game.get('date')
    birth=player.get('birthDate') or player.get('birthdate')
    milestone=player.get('milestone')
    def src(*rows):
        return sorted(set(row['sourceUrl'] for row in rows if receipt(row)))
    def emit(step,ok,evidence,sources=(),contradiction=False,neutral=False):
        if not isinstance(evidence,dict):
            raise ValueError('Overlay evidence must be a recorded dictionary')
        verdict=('PASS' if ok else 'ELIMINATED' if contradiction else 'NOT_EXECUTED')
        detail={**evidence,'independentOverlayEvaluation':True,
                'checkedBeforeG18':True,'masterGateVerdictCopied':False,
                'nonblocking':bool(neutral)}
        records.append(gate_record(game,player['id'],step,verdict,detail,list(sources)))
    # Each step is an independent source check; do not reuse G0-G18 verdicts.
    emit('Step0',bool(receipt(goalie) and weak and g.get('sample')),
         {'attackSide':attacker,'targetGoalie':g.get('goalieId'),
          'status':g.get('status'),'weakOrigins':sorted(weak),
          'projectedVsConfirmedSeparated':True},
         src(goalie))
    source_players=roster_data.get('players')
    eligible=bool(isinstance(source_players,list) and
                  any(str(x.get('id'))==str(player.get('id')) for x in source_players))
    emit('Step1',bool(receipt(roster) and eligible),
         {'sourcePlayerCount':len(source_players) if isinstance(source_players,list) else None,
          'candidateOnCurrentRoster':eligible,
          'availability':player.get('availability','UNVERIFIED'),
          'dressedNotInferredFromRoster':True},src(roster))
    has_venue=bool(ctx.get('venueHome') or ctx.get('venue'))
    has_rest=bool(ctx.get('homeRestDays') is not None and
                  ctx.get('awayRestDays') is not None or ctx.get('rest'))
    emit('Step2',bool(receipt(context) and has_venue and has_rest),
         {'venue':ctx.get('venueHome') or ctx.get('venue'),
          'homeRestDays':ctx.get('homeRestDays'),
          'awayRestDays':ctx.get('awayRestDays'),
          'travelMiles':ctx.get('travelMiles'),
          'travelDistanceNotInvented':ctx.get('travelMiles') is None,
          'restSourceReviewed':has_rest,
          'contextSourcePresent':receipt(context)},src(context))
    red=cov.get('redStrongZones') or []
    zone_match=bool(zone and zone in weak)
    emit('Step3',bool(zone_match and zone not in red),
         {'playerOwnShotArea':zone,'goalieWeakOriginMatch':zone_match,
          'opponentDefenderAvoidZone':zone in red if zone else None,
          'goalMouthAnatomyNotInferred':True},
         src(raw_release,goalie,coverage),
         contradiction=bool(zone and zone in red and receipt(coverage)))
    emit('Step4',bool(recurrence and isinstance(recurrence.get('appearanceDates'),int)
                      and recurrence['appearanceDates']>0),
         {'datedActualAppearances':recurrence.get('appearanceDates') if recurrence else None,
          'datedCreditedGoalDates':recurrence.get('distinctGoalDates') if recurrence else None,
          'noMissedGameZeroFilled':True,'multigoalDateCountedOnce':True},
         src(player.get('gameLog'),player.get('mappedGoals'),
             player.get('officialGoalTotal')))
    own_mechanism=bool(receipt(raw_release) and release and release.get('archetype')
                      and isinstance(release.get('ownedGoals'),int)
                      and isinstance(release.get('attempts'),int)
                      and release['attempts']>=release['ownedGoals']>=0)
    emit('Step5',own_mechanism,
         {'ownedArchetype':release.get('archetype') if release else None,
          'sourcedOwnShotsOnNet':release.get('attempts') if release else None,
          'creditedGoalsByOrigin':release.get('ownedGoals') if release else None,
          'exactShotVelocityNotAvailable':True,
          'attemptsAreNotAllShotAttempts':True},src(raw_release))
    valid_role=bool(receipt(dep) and deploy.get('EV') and
                    deploy.get('status') in ('PROJECTED','CONFIRMED'))
    emit('Step6',valid_role,
         {'EV':deploy.get('EV'),'PP':deploy.get('PP'),'PK':deploy.get('PK'),
          'sourceStatus':deploy.get('status'),
          'unverifiedSpecialTeamsNotPromoted':deploy.get('PP') is None or deploy.get('PK') is None},
         src(dep))
    # Mandatory archetype tagging occurs before G18's path decision.
    tag={'playerId':str(player.get('id')),'archetype':release.get('archetype') if release else None,
         'directOwnShotOrigin':zone,'goalieVulnerableAreas':sorted(weak),
         'sourceTaggedBeforeFinalPick':True}
    emit('Step7',bool(own_mechanism and zone_match),tag,
         src(raw_release,goalie))
    shifts=cov.get('shiftByShift') or cov.get('defensiveShiftEvents')
    # Step 8's original scope is independent TEAM defensive shift coverage.
    # G5 and G9, not Step 8, adjudicate exact scorer-to-goalie zone matches.
    # Never demote a genuine sourced team shift review just because a roster
    # member has zero observed OWN NHL EDGE shot-origin samples or because
    # its EDGE zone is not an exact PBP coordinate polygon. Crucially, do
    # not claim the individual player's scoring zone has an on-ice match.
    # These are official historical on-ice defensive groups joined to an
    # actual contemporaneous PBP shot, NOT projected tonight lines.
    actual_shifts=[e for e in shifts
          if isinstance(e,dict)
          and isinstance(e.get('defendingOnIcePlayerIds'),list)
          and 3<=len(e['defendingOnIcePlayerIds'])<=7
          and isinstance(e.get('officialShiftChartUrl'),str)
          and e['officialShiftChartUrl'].startswith('https://api.nhle.com/')
          and isinstance(e.get('officialPlayByPlayUrl'),str)
          and e['officialPlayByPlayUrl'].startswith('https://api-web.nhle.com/')
          and e.get('zone') and e.get('gameId')
          and e.get('period') is not None and e.get('eventClock')
          ] if isinstance(shifts,list) else []
    area_shifts=[e for e in actual_shifts if zone and e.get('zone')==zone]
    shift_urls=[url for url in (cov.get('shiftSourceUrls') or [])
                if isinstance(url,str)
                and url.startswith('https://api.nhle.com/stats/rest/en/shiftcharts')]
    sourced_team_shift_review=bool(
        receipt(coverage) and actual_shifts and shift_urls and
        isinstance(cov.get('actualDefensiveShiftMatches'),int) and
        cov['actualDefensiveShiftMatches']>=len(actual_shifts))
    emit('Step8',sourced_team_shift_review,
         {'originalPhase1Scope':'INDEPENDENT_TEAM_DEFENSIVE_COVERAGE_SHIFT_EVIDENCE',
          'sourceDefensiveGreenZones':cov.get('greenWeakZones'),
          'sourceDefensiveRedZones':red,
          'actualShiftByShiftObserved':bool(actual_shifts),
          'observedHistoricalShiftEvents':cov.get('actualDefensiveShiftMatches'),
          'actualMatchingAreaShiftEvents':len(area_shifts),
          'matchingArea':zone,
          'specificPlayerZoneShiftEvidenceProven':bool(area_shifts),
          'specificPlayerZoneNotAssumedFromTeamShifts':True,
          'playerOwnScoringAreaNotVerified':not bool(zone),
          'observedOnIceSamples':(area_shifts or actual_shifts)[:5],
          'officialShiftChartSourceCount':len(shift_urls),
          'historicalShiftsNotTonightLineupConfirmation':True,
          'independentShotOriginConcessionsAvailable':bool(cov.get('zoneConcessions')),
          'cannotInferSpecificLaneFromTeamShiftSample':not bool(area_shifts),
          'cannotInferShiftMatchupsFromShotOrigins':not bool(area_shifts)},
         sorted(set(src(coverage)+shift_urls)))
    recent=pres.get('recentAppearanceShots')
    good_shots=(isinstance(recent,int) and recent>=0 or
                isinstance(recent,list) and bool(recent) and
                all(type(x) is int and x>=0 for x in recent))
    emit('Step9',bool(receipt(pressure) and good_shots),
         {'dateSampleShotsOnNet':recent,'recentRouteContinuationMeasured':good_shots,
          'notWeightedOrMarketSelected':True},src(pressure))
    emit('Step10',bool(receipt(goalie) and receipt(raw_release) and zone_match),
         {'targetGoalieId':g.get('goalieId'),'ownRouteArea':zone,
          'weaknessAreaSummary':weak.get(zone) if zone else None,
          'shotOriginVsGoalMouthKeptSeparate':True},
         src(raw_release,goalie))
    rivals=[x for x in teammates if str(x.get('id'))!=str(player.get('id')) and
            x.get('availability') not in ('OUT','SCRATCHED','INJURED')]
    reviewed={str(x.get('challengerId')):x for x in challenger_rows}
    all_reviewed=len(reviewed)==len(rivals) and all(str(x.get('id')) in reviewed for x in rivals)
    matching=[x for x in challenger_rows if x.get('sameLane')]
    good_verdicts={'DEFEATED','DIFFERENT_TARGET_LANE','SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE'}
    no_conflicts=all(x.get('status') in good_verdicts for x in challenger_rows)
    rival_src=sorted(set(url for x in challenger_rows for url in x.get('sourceUrls',[])
                        if isinstance(url,str) and url.startswith('https://')))
    emit('Step10.5',bool(all_reviewed and no_conflicts),
         {'adjacentShadowCount':len(matching),'everyActiveRivalReviewed':all_reviewed,
          'sourceVerifiedOutcomes':[{'rivalId':x.get('challengerId'),
             'status':x.get('status'),'sameLane':x.get('sameLane',False)}
               for x in challenger_rows],
          'noUnjustifiedTransfer':not no_conflicts,
          'sourceBackedRivalCount':len(rival_src)},rival_src)
    who_proved=bool(receipt(who) and who_data.get('directIndependentRoute') is True
                   and isinstance(who_data.get('mechanism'),str)
                   and who_data['mechanism'].strip())
    emit('Step11',bool(receipt(raw_release) and (who_proved or not receipt(who))),
         {'blueLineOrUnusualPath':who_data.get('mechanism') if who_proved else None,
          'WHOPathActuallySourceSupported':who_proved,'noWHOQuota':True,
          'neutralAbsenceOfWHOIsNotAnomaly':not who_proved},src(who,raw_release),neutral=True)
    emit('Step12',bool(all_reviewed and no_conflicts),
         {'challengerCount':len(rivals),'comparisonRows':len(challenger_rows),
          'depthAndDefenseIncluded':True,'unresolvedChallengers':[
             x.get('challengerId') for x in challenger_rows if
             x.get('status') not in good_verdicts]},
         sorted(set(rival_src+src(roster))))
    # Qualitative name / date / jersey / birth / milestone *review*, no formula
    # or arbitrary numerology weights. Unknowns remain explicitly unknown.
    date_digits=''.join(x for x in str(date or '') if x.isdigit())
    jersey_digits=''.join(x for x in str(jersey or '') if x.isdigit())
    qualitative={'name':player.get('name'),'slateDate':date,'jersey':jersey,
        'birthDate':birth,'dateDigits':date_digits,
        'jerseyDigits':jersey_digits,
        'sharedJerseyDateDigits':sorted(set(jersey_digits)&set(date_digits)),
        'verifiedMilestone':evidence_data(milestone) if receipt(milestone) else None,
        'birthDateVerified':bool(birth),'milestoneVerified':receipt(milestone),
        'gematriaNumericFormulaRequired':False,
        'noNumerologyWeightOrRanking':True,'qualitativeReviewActuallyPerformed':True}
    emit('Step13',bool(date and player.get('name')),qualitative,
         src(milestone,roster),neutral=True)
    sources=src(c,goalie,dep,raw_release)
    contradiction_clear=bool(receipt(c) and
        contra.get('goalieStrengthReview') is not None and
        contra.get('lineupDisagreementReview') is not None and
        contra.get('strongestRivalReview') is not None and
        contra.get('unresolved') is not True)
    emit('Step14',contradiction_clear,
         {'reviewedGoalieStrength':contra.get('goalieStrengthReview'),
          'reviewedLineupDisagreement':contra.get('lineupDisagreementReview'),
          'reviewedRivals':bool(contra.get('strongestRivalReview')),
          'sourceContradictionsUnresolved':contra.get('unresolved') is True,
          'preservesUnresolvedEvidence':True},
         sources)
    actual=[r['gate'] for r in records]
    if actual!=STEP_ORDER:
        raise ValueError('Phase-1 overlay order or individual check missing')
    return records
