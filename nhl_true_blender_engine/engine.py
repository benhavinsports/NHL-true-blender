"""Evidence-driven NHL G0..G18 executor. No favorites, arbitrary weights or proxy goalies.

Input is a source-annotated game snapshot produced by collectors, not a list of picks.
Output is an immutable gate record for every surveyed direction and skater.
Only the uniquely defensible, fully evidenced survivors can be published.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from .storage import save_card, save_gates, log_job, get_card, fingerprint
from .overlay_checks import independent_overlay, STEP_ORDER
from .semantic_certification import audit_gate

# The user's 18 numbered scorer gates remain individually named and ordered.
# G10.5 is the mandatory half-step between G10 and G11. G0 is the
# separate goalie-first direction decision, not a substitute for scorer gates.
SCORER_GATE_ORDER = ([f'G{i}' for i in range(1,11)] +
                     ['G10.5'] + [f'G{i}' for i in range(11,19)])
MASTER = ['G0'] + SCORER_GATE_ORDER
OVERLAY = ([f'Step{i}' for i in range(11)] + ['Step10.5'] +
           [f'Step{i}' for i in range(11,15)])
# Execution order reflects the real dependency: G0, G1-G17 (including G10.5),
# every independent overlay step in its own exact order, then final G18.
EXECUTION_ORDER = MASTER[:-1] + OVERLAY + [MASTER[-1]]
if MASTER != ['G0'] + SCORER_GATE_ORDER or EXECUTION_ORDER[-1] != 'G18':
    raise RuntimeError('Authoritative NHL gate order was altered')
PATCH_IDS = (
    'PATCH_PROVENANCE_V1','PATCH_START_TIME_V1','PATCH_OFFICIAL_SCORERS_V1',
    'PATCH_GATE13_CONTINUITY_V1','PATCH_RECIPIENT_LOCK_V1',
    'PATCH_2026_11_05_EXECUTION_MATRIX_V1','PATCH_G10_5_G16_COMPARE_V2',
    'PATCH_HISTORICAL_MULTIVERSION_OCT08_10_V1','TBL-G105-G17-2026-11-08',
    'UTA-G105-G17-2026-11-08','PATCH-NOV12-G10.5-EXPLICIT-SEPARATION',
    'PATCH-NOV12-G0-GOALIE-BRANCH-INTEGRITY','PATCH-NOV12-G7-MAP-COVERAGE-INTEGRITY'
)
GATE_PATCHES = {
    'G0':['PATCH_2026_11_05_EXECUTION_MATRIX_V1','PATCH-NOV12-G0-GOALIE-BRANCH-INTEGRITY'],
    'G1':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G2':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G3':['PATCH-NOV12-G0-GOALIE-BRANCH-INTEGRITY'],
    'G4':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G5':['PATCH-NOV12-G0-GOALIE-BRANCH-INTEGRITY'],
    'G6':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G7':['PATCH-NOV12-G7-MAP-COVERAGE-INTEGRITY','PATCH_OFFICIAL_SCORERS_V1'],
    'G8':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G9':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G10':['PATCH_OFFICIAL_SCORERS_V1','PATCH_RECIPIENT_LOCK_V1'],
    'G10.5':['PATCH-NOV12-G10.5-EXPLICIT-SEPARATION','PATCH_G10_5_G16_COMPARE_V2',
             'TBL-G105-G17-2026-11-08','UTA-G105-G17-2026-11-08'],
    'G11':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G12':['PATCH_OFFICIAL_SCORERS_V1','PATCH_RECIPIENT_LOCK_V1'],
    'G13':['PATCH_GATE13_CONTINUITY_V1'],
    'G14':['PATCH_2026_11_05_EXECUTION_MATRIX_V1'],
    'G15':['PATCH_RECIPIENT_LOCK_V1'],
    'G16':['PATCH-NOV12-G10.5-EXPLICIT-SEPARATION','PATCH_G10_5_G16_COMPARE_V2'],
    'G17':['PATCH-NOV12-G0-GOALIE-BRANCH-INTEGRITY','PATCH_PROVENANCE_V1',
           'PATCH_START_TIME_V1','TBL-G105-G17-2026-11-08','UTA-G105-G17-2026-11-08'],
    'G18':['PATCH_RECIPIENT_LOCK_V1','PATCH_START_TIME_V1',
           'PATCH_HISTORICAL_MULTIVERSION_OCT08_10_V1','PATCH_PROVENANCE_V1']
}



def receipt(value):
    """Only independently attributed, time-stamped observations qualify."""
    return (isinstance(value, dict)
            and isinstance(value.get('sourceUrl'), str) and value['sourceUrl'].startswith('https://')
            and isinstance(value.get('observedAt'), str) and bool(value['observedAt'])
            and bool(value.get('data')))


def evidence_data(value, key=None):
    if not receipt(value): return None
    return value['data'] if key is None else value['data'].get(key)


def verdict(pass_value, detail, eliminated=False):
    return ('PASS' if pass_value else ('ELIMINATED' if eliminated else 'NOT_EXECUTED'), detail)


def gate_record(game, player, gate, disposition, detail, source_ids=None):
    if gate not in EXECUTION_ORDER:
        raise ValueError(f'Unknown gate outside the authoritative execution order: {gate}')
    index=EXECUTION_ORDER.index(gate)
    phase=('G0_GOALIE_FIRST' if gate=='G0' else
           'OVERLAY' if gate in OVERLAY else
           'G18_FINAL' if gate=='G18' else 'MASTER')
    return {'gameId':str(game['id']),'playerId':str(player),'gate':gate,
            'disposition':disposition,
            'details':{'evidence':detail,'sourceIds':source_ids or [],
                       'appliedPatches':GATE_PATCHES.get(gate,[]),
                       'executionIndex':index,'executionPhase':phase}}


def all_goalie_branches(game, stage):
    """No shortcut from one goalie profile to the opposing team's goalie."""
    by_team = {}
    for team in (game['away'],game['home']):
        branches=[]
        for b in game.get('goalies',{}).get(team,[]):
            if not receipt(b):continue
            d=b['data']
            if d.get('status') not in ('PROJECTED','EXPECTED','CONFIRMED'):
                continue
            branches.append(b)
        # A confirmed goalie replaces its expected branch, but an unconfirmed
        # matchup must retain its evidence-labelled EXPECTED/PROJECTED branch.
        # CONFIRMED describes the run phase, never an invented source status.
        # A genuinely CONFIRMED starter supersedes projected/expected
        # alternatives in either run phase. The old stage-only filter left
        # two alleged starters in PROJECTED, despite an independently
        # confirmed name, and G0 then failed before evaluating skaters.
        confirmed=[b for b in branches if b['data'].get('status')=='CONFIRMED']
        if confirmed:
            branches=confirmed
        superseded={str(b['data']['supersedesGoalieId']) for b in branches
                    if b['data'].get('status')=='CONFIRMED' and b['data'].get('supersedesGoalieId')}
        by_team[team]=[b for b in branches if str(b['data'].get('goalieId')) not in superseded]
    return by_team


def g0_full_slate(games, stage):
    scan=[]; error=[]
    for game in games:
        for attacker,defender in ((game['away'],game['home']), (game['home'],game['away'])):
            branches=all_goalie_branches(game,stage).get(defender,[])
            proofs=[]
            for src in branches:
                x=src['data']; weak=x.get('weakZones',{})
                # A source-proven STRONG goalie has NO weak zones but still
                # has a measured independent G0 profile. Do not erase the
                # negative/strong goalie receipt or choose the other side
                # simply because this goalie lacked a weak zone.
                source_reviewed=(bool(weak) and bool(x.get('sample')) and
                                 x.get('counterevidence') is not None) or bool(
                    x.get('sourceReviewed') is True or
                    (x.get('sourceClass')=='INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY'
                     and x.get('fullySourceComparedAreas',0)>0))
                sample_peer=game.get('goaliePeerContexts',{}).get(str(x.get('goalieId')))
                proof={'goalieId':x.get('goalieId'),'status':x.get('status'),
                       'sourceUrl':src['sourceUrl'],'observedAt':src['observedAt'],
                       'weakZones':weak,'strengthZones':x.get('strengthZones',{}),
                       'counterevidence':x.get('counterevidence'),
                       'sample':x.get('sample'),
                       'profileReviewed':source_reviewed,
                       'evidenceScope':x.get('evidenceScope') or x.get('sourceType'),
                       'sourceClass':x.get('sourceClass'),
                       'goalieProfileSourceUrl':x.get('goalieProfileSourceUrl'),
                       'sameCohortPbp':sample_peer,
                       'goalieTeam':defender}
                proofs.append(proof)
            complete=bool(proofs) and all(p['profileReviewed'] and bool(p['sample'])
                    and p['counterevidence'] is not None for p in proofs)
            scan.append({'gameId':str(game['id']),'attacker':attacker,'defender':defender,
                         'targetGoalies':proofs,'goalieProfileEvidenced':complete,
                         'attackableWeakZoneFound':any(bool(p['weakZones']) for p in proofs),
                         'oppositeDirectionMustAlsoBeReviewed':True})
            if not complete:error.append(f"G0 {game['id']} {attacker} attacking {defender}: independent source-backed goalie sample or peer review incomplete")
    return scan,error


def complete_roster(game, team):
    """Current roster is not a confirmed dressed lineup. Never silently drop depth or D."""
    wrapper=game.get('rosters',{}).get(team)
    if not receipt(wrapper):return []
    players=wrapper['data'].get('players',[])
    unique={}
    for p in players:
        if not p.get('id') or not p.get('position'):
            continue
        if p['position'] not in ('C','L','R','LW','RW','D'):
            continue  # Goalies are not goal-scoring skater candidates
        if str(p['id']) in unique:
            raise ValueError('G2 duplicate skater in roster')
        unique[str(p['id'])]=p
    return list(unique.values())


def player_releases(p):
    b=p.get('release')
    if not receipt(b):return None
    data=b['data']
    if not (data.get('archetype') and data.get('zone') and isinstance(data.get('attempts'), int)
            and isinstance(data.get('ownedGoals'),int)):
        return None
    return data




def release_matched_to_g0_target(player,goalie_profile,defensive_coverage=None):
    """After G0 selects an attack side, match each skater's independently
    observed OWN shot-origin routes to that goalie's evidenced weak origins.

    Neither G0 nor the original release source is edited; no famous-player
    shortcut. A different goalie branch gets its own independent comparison.
    """
    wrapper=player.get('release')
    if not receipt(wrapper):
        return player
    base=wrapper['data']
    routes=base.get('allRoutes')
    weak=goalie_profile.get('data',{}).get('weakZones') or {}
    if not isinstance(routes,list) or not routes or not weak:
        return player
    matching=[r for r in routes if r.get('zone') in weak
              and isinstance(r.get('sog'),int)
              and isinstance(r.get('ownedGoals'),int)
              and r['sog']>=r['ownedGoals']>=0]
    if not matching:
        return player
    # G0 remains first. Among the player's OWN observed shots against G0's
    # goalie weakness, find a route independently supported by G9's actual
    # opponent-defense shot-origin concessions. Do not force a mismatch merely
    # because the skater scored more historical goals from another goalie-weak
    # area. Every eligible route still requires separately verified G5/G9.
    defense=(defensive_coverage.get('data') or {}) if receipt(defensive_coverage) else {}
    green=set(defense.get('greenWeakZones') or [])
    jointly_sourced=[x for x in matching if x['zone'] in green]
    considered=jointly_sourced if jointly_sourced else matching
    considered.sort(key=lambda x:(x['ownedGoals'],x['sog']),reverse=True)
    top=considered[0]
    tied=[x for x in considered if
          (x['ownedGoals'],x['sog'])==(top['ownedGoals'],top['sog'])]
    if len(tied)>1:
        # No arbitrary zone tie break. The original independently sourced
        # release remains the candidate until another gate separates lanes.
        return player
    observed=dict(base)
    observed.update({
        'archetype':base.get('archetype') or 'OBSERVED_OWN_SHOT_ORIGIN',
        'zone':top['zone'],
        'attempts':top['sog'],
        'ownedGoals':top['ownedGoals'],
        'g0MatchedOwnOriginRoute':True,
        'g9DefensiveLaneIndependentlyMatched':bool(jointly_sourced),
        'g9CoverageSourceUrl':defensive_coverage.get('sourceUrl') if jointly_sourced else None,
        'consideredOwnGoalieWeakRoutes':sorted(x['zone'] for x in matching),
        'originalPrimaryOrigin':base.get('zone'),
        'primaryWasTiedBeforeG0':not bool(base.get('canDeterminePrimary',True)),
        'candidateRouteReconstructedFrom':wrapper['sourceUrl'],
        'anatomicalPlacementCertified':False,
        'noPreG0SkaterPreference':True
    })
    result=dict(player)
    result['release']={**wrapper,'data':observed}
    return result

def reconcile_logs(p):
    """Aggregate only actual appearances and official dated goal events; no missed game zeros."""
    logs=p.get('gameLog'); events=p.get('mappedGoals'); total=p.get('officialGoalTotal')
    if not (receipt(logs) and receipt(events) and receipt(total)):
        return None
    ld=logs['data']; ed=events['data']; td=total['data']
    if not isinstance(ld.get('appearances'),list) or not isinstance(ed.get('goals'),list):return None
    if not isinstance(td.get('goals'),int):return None
    goals=ed['goals']; seen=set()
    for goal in goals:
        if not goal.get('goalId') or not goal.get('date') or goal['goalId'] in seen or not goal.get('sourceUrl'):
            return None
        seen.add(goal['goalId'])
    if len(goals)!=td['goals']:
        return None
    dates={e['date'] for e in goals}
    appearance_dates={x.get('date') for x in ld['appearances']}
    if not dates.issubset(appearance_dates):return None
    return {'appearanceDates':len(appearance_dates),'distinctGoalDates':len(dates),
            'officialGoals':td['goals'],'eventCount':len(goals),
            'lastAppearances':ld['appearances'][:10]}


def challenger_proof(candidate, challengers, goalie_weak_zones, defense_weak_zones=None):
    """Compare *every* skater's owned same-origin finishing route, not fame/PP1.

    NHL EDGE independently measures each skater's shots on goal and own goals
    in each area. Requiring every competitor's separate prior-game goal log
    would discard a real same-lane threat merely because that player hasn't
    scored in the sampled last-eight games; the rival's observed season zone
    data remains valid challenger evidence.

    G10.5 compares DIRECT credited goals from the exact same target area
    before shot volume (which is supporting pressure, not a scored goal).
    This is categorical, source-linked separation with NO ranking weights;
    equal own-goal counts are compared on observed SOG, and equal results
    remain unresolved. All teammates and alternative routes remain audited.
    """
    base=player_releases(candidate)
    rows=[]; all_defeated=True
    if not base:
        return None,[]
    for rival in challengers:
        if str(rival['id'])==str(candidate['id']):
            continue
        wrapper=rival.get('release')
        release=player_releases(rival)
        if not release and receipt(wrapper) and isinstance(wrapper['data'].get('allRoutes'),list):
            # A tied season top area is still a valid measured SAME-LANE
            # challenger. Use the observed route in candidate's exact zone
            # instead of erasing the competing player.
            release=wrapper['data']
        if not release:
            zero=rival.get('zeroShotOriginProof')
            zdata=evidence_data(zero)
            if (receipt(zero) and
                zdata.get('sourceType') in (
                    'NHL_EDGE_SKATER_SHOT_ORIGIN_CURRENT_SEASON',
                    'NHL_OFFICIAL_PLAYER_DATED_REGULAR_SEASON_GAME_LOG') and
                zdata.get('verifiedNoSameLaneOnNetRoute') is True and
                zdata.get('observedOnNetShotsAcrossAllReportedOrigins')==0 and
                zdata.get('ownedGoalsAcrossAllReportedOrigins')==0):
                # All roster teammates were scanned. This official EDGE
                # season-zero player has NO evidenced direct scoring
                # shots in the candidate's specific rink lane, not a
                # phantom comparison rival. Do not claim he cannot score
                # for the first time tonight or fabricate a G4 route.
                rows.append({'challengerId':str(rival['id']),
                             'status':'SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE',
                             'sourceUrls':[zero['sourceUrl']],
                             'evidenceId':zero.get('evidenceId'),
                             'noClaimOfFutureScoringImpossibility':True,
                             'sourceVerifiedZeroShotSeason':True,
                             'sourceEvidenceType':zdata.get('sourceType')})
                continue
            rows.append({'challengerId':str(rival['id']),
                         'status':'NO_RELEASE_SOURCE',
                         'notExcludedForMissingSampledGameLog':True})
            all_defeated=False
            continue
        if not receipt(wrapper):
            rows.append({'challengerId':str(rival['id']),
                         'status':'RELEASE_PROVENANCE_MISSING'})
            all_defeated=False
            continue
        # A rival does not become a defeated goal recipient merely because
        # its best scoring route differs from this candidate's route. G0 can
        # identify MULTIPLE independently weak areas for the same goalie.
        # G10.5 must compare the rival's strongest actually recorded OWN
        # finishing route through ANY jointly viable G0+G9 area.
        # Earlier code ignored goalie_weak_zones entirely and compared only
        # the candidate's lane, falsely defeating other direct recipients.
        all_routes=release.get('allRoutes') or []
        if not all_routes and release.get('zone'):
            all_routes=[{'zone':release['zone'],'sog':release.get('attempts'),
                         'ownedGoals':release.get('ownedGoals')}]
        goalie_areas=set(goalie_weak_zones or {})
        defensive_areas=(set(defense_weak_zones)
                         if defense_weak_zones is not None else None)
        viable=[x for x in all_routes if
                x.get('zone') in goalie_areas and
                (defensive_areas is None or x['zone'] in defensive_areas) and
                type(x.get('sog',x.get('attempts'))) is int and
                type(x.get('ownedGoals')) is int and
                x.get('sog',x.get('attempts'))>=x.get('ownedGoals')>=0]
        if not viable:
            rows.append({'challengerId':str(rival['id']),
                         'status':'DIFFERENT_TARGET_LANE',
                         'candidateZone':base['zone'],
                         'rivalKnownAreas':[x.get('zone') for x in all_routes],
                         'G0GoalieWeakZones':sorted(goalie_areas),
                         'G9DefensiveWeakZones':sorted(defensive_areas) if defensive_areas is not None else None,
                         'noneOfKnownRivalOriginsJointlyMatchG0G9':True,
                         'notEvidenceRivalCannotScoreTonight':True,
                         'sourceUrls':[wrapper['sourceUrl']]})
            continue
        # Own direct goal credit first; on-net shots break only goal ties.
        # Routes with exactly matching evidence do not require an arbitrary
        # choice to compare THIS rival with the candidate.
        priority=lambda x:(x['ownedGoals'],x.get('sog',x.get('attempts')))
        target=max(viable,key=priority)
        tied_zones=sorted({x['zone'] for x in viable if priority(x)==priority(target)})
        opponent_shots=target.get('sog',target.get('attempts'))
        opponent_goals=target.get('ownedGoals')
        if (not isinstance(opponent_shots,int) or
                not isinstance(opponent_goals,int) or
                opponent_goals<0 or opponent_shots<opponent_goals):
            rows.append({'challengerId':str(rival['id']),
                         'status':'INCOMPLETE_OWN_FINISH_DATA',
                         'sourceUrl':wrapper['sourceUrl']})
            all_defeated=False
            continue
        # G10.5 is DIRECT RECIPIENT separation, not a requirement for a
        # scorer to lead every teammate in BOTH shots and goals. A skater
        # with 7 actual goals on this lane is not disproved by a teammate
        # with 6 actual goals and more harmless on-net shots.
        # Compare OWN credited goals first; use SOG only if the OWN goal
        # counts are equal. No fame/PP status/odds or numeric weights.
        candidate_direct=(base['ownedGoals'],base['attempts'])
        rival_direct=(opponent_goals,opponent_shots)
        dominates=candidate_direct>rival_direct
        defeated_by=rival_direct>candidate_direct
        if not dominates:
            all_defeated=False
        rows.append({
            'challengerId':str(rival['id']),
            'status':'DEFEATED' if dominates else
                     'RIVAL_DOMINATES' if defeated_by else
                     'NO_DECISIVE_ROUTE_SEPARATION',
            'candidate':{'zone':base['zone'],'shotsOnGoal':base['attempts'],
                         'ownedGoals':base['ownedGoals']},
            'challenger':{'zone':target['zone'],'shotsOnGoal':opponent_shots,
                          'ownedGoals':opponent_goals},
            'sourceUrls':[candidate['release']['sourceUrl'],wrapper['sourceUrl']],
            'sameLane':target['zone']==base['zone'],
            'rivalAlternateGoalieWeakLane':target['zone']!=base['zone'],
            'allRivalJointlyViableZones':sorted({x['zone'] for x in viable}),
            'jointlyViableRouteTiedZones':tied_zones,
            'goalieWeaknessAndDefenseBothRequired':defensive_areas is not None,
            'rivalEVRole':evidence_data(rival.get('deployment')),
            'roleReviewIncomplete':not receipt(rival.get('deployment')),
            'noSeasonTotalInvented':True,
            'comparisonPriority':['ownedGoalsFromSameShotOrigin','onNetShotPressureOnlyWhenGoalsEqual'],
            'noFameOddsOrPPShortcut':True,
            'rule':'direct same-origin NHL EDGE credited own goals; when tied use same-origin on-net shots, never combined weights',
        })
    return all_defeated,rows

def adjudicate_scoring_path(player, teammates, release, goalie_profile, coverage,
                            dispositions, challenger_rows, who_supported):
    """Determine PRIMARY / TRANSFER / WHO from positive gate evidence only.

    This runs AFTER G0, direct route, goal recipient, G10.5 and G17 decisions.
    Never fill a label quota; never label the lack of WHO/TRANSFER as PRIMARY.
    Requiring direct evidence for each named path prevents the old automatic
    'else PRIMARY' behavior.
    """
    own=evidence_data(player.get('finishOwnership')) or {}
    goalie_data=evidence_data(goalie_profile) or {}
    cover=evidence_data(coverage) or {}
    zone=(release or {}).get('zone')
    all_gates=all(dispositions.get(g,{}).get('disposition')=='PASS'
                  for g in ('G0','G3','G4','G5','G6','G7','G9',
                            'G10','G10.5','G12','G15','G16','G17'))
    direct={
        'G0ThruG17SourcePass':all_gates,
        'independentOwnScoringSource':receipt(player.get('release')),
        'observedOwnedGoalsInSelectedLane':bool(release and
            type(release.get('ownedGoals'))==int and release['ownedGoals']>0),
        'goalieWeakAreaDirectlyMatched':bool(zone and zone in (goalie_data.get('weakZones') or {})),
        'independentDefenseAreaDirectlyMatched':bool(zone and zone in
            (cover.get('greenWeakZones') or [])),
        'historicallyCreditedIndependentGoalRecipient':bool(
            own.get('recipient') is True and
            own.get('creditedGoalsVerified') is True and
            receipt(player.get('release')) and
            type((release or {}).get('ownedGoals')) is int and
            release['ownedGoals']>0 and
            dispositions.get('G15',{}).get('disposition')=='PASS'),
        'allRelevantChallengersReviewed':bool(dispositions.get('G10.5',{}).get('disposition')=='PASS'
            and dispositions.get('G16',{}).get('disposition')=='PASS'),
        'opponentContradictionsReviewed':bool(dispositions.get('G17',{}).get('disposition')=='PASS'),
        'verifiedEVAccess':receipt(player.get('deployment')),
    }
    route_direct=all(direct.values())
    original=(release or {}).get('originalPrimaryOrigin')
    changed_lane=bool(original and original!=zone)
    primary_source_lane=not changed_lane and not (release or {}).get('primaryWasTiedBeforeG0',False)
    approved_rivals=[]
    defeated={str(x.get('challengerId')):x for x in challenger_rows
              if x.get('status')=='DEFEATED' and x.get('sameLane')}
    for rival in teammates:
        rid=str(rival.get('id'))
        proof=defeated.get(rid)
        if not proof:
            continue
        rival_primary=player_releases(rival)
        if not rival_primary or rival_primary.get('zone')!=zone:
            continue
        if not receipt(rival.get('release')):
            continue
        rival_direct=proof.get('challenger') or {}
        base_direct=proof.get('candidate') or {}
        if (rival_primary.get('ownedGoals',0)>0 and
            type(rival_direct.get('ownedGoals'))==int and
            type(base_direct.get('ownedGoals'))==int and
            (base_direct['ownedGoals'],base_direct.get('shotsOnGoal',0))>
            (rival_direct['ownedGoals'],rival_direct.get('shotsOnGoal',0))):
            approved_rivals.append({
                'displacedDirectPrimaryPlayerId':rid,
                'sameLane':zone,
                'directGoalCreditCandidate':base_direct['ownedGoals'],
                'directGoalCreditPrior':rival_direct['ownedGoals'],
                'rivalOriginalPrimaryOrigin':rival_primary['zone'],
                'sourceUrls':sorted(set(filter(None,proof.get('sourceUrls',[])))),
                'G10_5Verdict':proof['status'],
            })
    # A source can separately verify the prior primary losing the same route;
    # a naked Boolean without a sourced G10.5 defeated rival is insufficient.
    transfer=player.get('transferEvidence')
    tdata=evidence_data(transfer) or {}
    supplied_displaced=(str(tdata.get('displacedPlayerId')) if
                        tdata.get('displacedPlayerId') is not None else None)
    confirmed_displacement=(receipt(transfer) and
        tdata.get('directRouteDisplaced') is True and
        tdata.get('routeZone')==zone and
        any(x['displacedDirectPrimaryPlayerId']==supplied_displaced
            for x in approved_rivals))
    derived_displacement=bool(changed_lane and approved_rivals)
    who=player.get('whoAnomaly')
    who_data=evidence_data(who) or {}
    physical_anomaly=bool(who_supported and receipt(who) and
        who_data.get('directIndependentRoute') is True and
        isinstance(who_data.get('mechanism'),str) and who_data['mechanism'].strip() and
        direct['goalieWeakAreaDirectlyMatched'] and
        direct['independentDefenseAreaDirectlyMatched'] and all_gates)
    # If two different source-supported mechanisms compete, even the path
    # label must survive contradiction review; there is no WHO-over-TRANSFER
    # priority or arbitrary fallback ordering.
    path_contradiction=bool(physical_anomaly and
        (confirmed_displacement or derived_displacement))
    if path_contradiction:
        path=None
        rationale='Two different sourced physical paths remain unseparated; no preferred label assigned'
    elif physical_anomaly:
        path='WHO'
        rationale='Sourced independent anomaly scoring mechanism survived G14, goalie route and full gates'
    elif route_direct and (confirmed_displacement or derived_displacement):
        path='TRANSFER'
        rationale='Own secondary scoring route defeated independently sourced same-lane original PRIMARY recipient under G10.5'
    elif route_direct and primary_source_lane and not tdata.get('directRouteDisplaced'):
        path='PRIMARY'
        rationale='Independently sourced direct own-goal recipient and primary lane survived goalie, defense and every challenger'
    else:
        path=None
        rationale='No independently sufficient evidence to certify PRIMARY, TRANSFER or WHO for this route'
    sources=sorted({x for x in (
        (player.get('release') or {}).get('sourceUrl'),
        (player.get('finishOwnership') or {}).get('sourceUrl'),
        (player.get('deployment') or {}).get('sourceUrl'),
        (goalie_profile or {}).get('sourceUrl'),
        goalie_data.get('goalieProfileSourceUrl'),
        (coverage or {}).get('sourceUrl'),
        (player.get('contradictions') or {}).get('sourceUrl'),
        (who or {}).get('sourceUrl') if path=='WHO' else None,
        (transfer or {}).get('sourceUrl') if confirmed_displacement else None,
    ) if isinstance(x,str) and x.startswith('https://')})
    sources=sorted(set(sources).union(
        x for rival in approved_rivals for x in rival['sourceUrls']))
    return path,{
        'path':path,'rationale':rationale,
        'scoringLane':zone,
        'originalScoringLane':original,
        'laneChangedAfterGoalieFirstG0':changed_lane,
        'primaryOriginIsSourceDistinct':primary_source_lane,
        'positiveDirectGateEvidence':direct,
        'futureAssistOrGoalOutcomeNeverProvedFromHistory':True,
        'G10_5DisplacedPrimaryEvidence':approved_rivals,
        'explicitDisplacementSourceValidated':bool(confirmed_displacement),
        'independentTransferDerivedFromG0AndG10_5':derived_displacement,
        'G14IndependentWhoAnomalyVerified':physical_anomaly,
        'competingWHOandTRANSFERPathsUnseparated':path_contradiction,
        'whoPhysicalMechanism':who_data.get('mechanism') if physical_anomaly else None,
        'sourceUrls':sources,
        'selectionIndependentOfLabel':True,
        'pathQuotaApplied':False,
        'fallbackToPrimary':False,
        'unknownIsNotAPath':True,
    }


def evaluate_skater(game, attack_team, player, teammates, goalie_profile, stage):
    d={}; proof=[]; deficient=[]; eliminated=False; first_elimination_gate=None
    weak=goalie_profile['data'].get('weakZones',{})
    strong=goalie_profile['data'].get('strengthZones',{})
    release=player_releases(player)
    rec=reconcile_logs(player)
    position=player.get('position')
    def emit(g, ok, detail, eliminate=False, source_ids=()):
        nonlocal eliminated,first_elimination_gate
        # Every candidate gets an ACTUAL G0-G18 source check. A previous
        # elimination is permanent, but it does NOT excuse skipping later
        # evidence checks or silently calling them completed.
        disp,content=verdict(ok,detail,eliminate)
        if disp=='PASS':
            gaps=audit_gate(g,content,list(source_ids),stage)
            if gaps:
                disp='NOT_EXECUTED'
                content={**content,'semanticProofGaps':gaps,
                         'evidenceReviewedButInsufficient':True}
        if first_elimination_gate:
            content={**content,'alreadyEliminatedAtGate':first_elimination_gate,
                     'laterPositiveEvidenceCannotReinstate':True}
        if disp=='ELIMINATED':
            eliminated=True
            if first_elimination_gate is None:first_elimination_gate=g
        elif disp=='NOT_EXECUTED':
            deficient.append(g)
        d[g]={'disposition':disp,'details':content}
        proof.append(gate_record(game,player['id'],g,disp,content,list(source_ids)))
    # G0's per-skater record must point to an attack direction already
    # adjudicated from BOTH goalies. A shared goalie profile is not itself
    # a completed first-gate decision.
    selected_direction=game.get('_g0SelectedDirection') or {}
    goalie_id=str(goalie_profile['data'].get('goalieId') or '')
    direction_ok=bool(
        selected_direction.get('attacker')==attack_team
        and selected_direction.get('defender') in (game['away'],game['home'])
        and any(str(b.get('goalieId'))==goalie_id
                for b in selected_direction.get('targetGoalies',[]))
        and selected_direction.get('goalieProfileEvidenced') is True)
    emit('G0',bool(direction_ok and weak and goalie_profile['data'].get('sample')
                   and goalie_profile['data'].get('counterevidence') is not None),
         {'targetGoalie':goalie_id,'attacker':attack_team,
          'branchStatus':goalie_profile['data'].get('status'),'weakZones':weak,
          'separateGoalieBranch':True,'directionSelectedBeforeSkaters':direction_ok,
          'selectedAttacker':selected_direction.get('attacker'),
          'selectedDefender':selected_direction.get('defender')},
         source_ids=list(filter(None,[
          goalie_profile['sourceUrl'],goalie_profile['data'].get('goalieProfileSourceUrl')])))
    context=evidence_data(game.get('context')) or {}
    has_venue=bool(context.get('venueHome') or context.get('venue'))
    has_rest=(isinstance(context.get('homeRestDays'),int)
              and isinstance(context.get('awayRestDays'),int)) or bool(context.get('rest'))
    context_ok=bool(receipt(game.get('context')) and has_venue and has_rest)
    emit('G1',context_ok,
         {'venueRestTravel':context if context else None,
          'venueReviewed':has_venue,'bothTeamRestReviewed':has_rest,
          'travelUnobservedNotInvented':context.get('travelDistanceNotInSource') is True
              or context.get('travelMiles') is None},
         source_ids=[game.get('context',{}).get('sourceUrl','')])
    roster=game.get('rosters',{}).get(attack_team)
    eligibility=player.get('availability','UNVERIFIED')
    # G2 surveys the WHOLE official current roster, not merely a lineup
    # publication's top lines. "UNVERIFIED" is roster eligibility to be
    # researched, NOT a confirmed dressed status or confirmed deployment.
    roster_member=bool(receipt(roster) and any(
        str(p.get('id'))==str(player.get('id'))
        for p in (roster['data'].get('players') or [])))
    roster_eligible=(roster_member and eligibility in
        ('DRESSED','CONFIRMED','PROJECTED_ACTIVE','UNVERIFIED'))
    emit('G2',bool(roster_eligible),
         {'candidateOnOfficialRoster':roster_member,
          'fullPoolSize':len(teammates),'availability':eligibility,
          'officialCurrentRosterSource':roster.get('sourceUrl') if receipt(roster) else None,
          'position':position,
          'currentRosterNotEquivalentToDressed':True,
          'confirmedDressed':eligibility in ('DRESSED','CONFIRMED'),
          'lineupStillRequiresIndependentG6':True},
         eliminate=eligibility in ('OUT','SCRATCHED','INJURED'),
         source_ids=[roster['sourceUrl']] if receipt(roster) else [])
    g3_reviewed=bool(direction_ok and weak and goalie_profile['data'].get('sample')
                      and goalie_profile['data'].get('counterevidence'))
    emit('G3',g3_reviewed,
         {'goalieSample':goalie_profile['data'].get('sample'),
          'goalieWeakZones':weak,
          'goalieStrengthZones':goalie_profile['data'].get('strengthZones'),
          'counterevidence':goalie_profile['data'].get('counterevidence'),
          'opposingGoalieBranchReviewed':direction_ok},
         source_ids=list(filter(None,[goalie_profile['sourceUrl'],
             goalie_profile['data'].get('goalieProfileSourceUrl')])))
    emit('G4',bool(release), {'archetype':release.get('archetype') if release else None,
         'ownRelease':release},source_ids=[player.get('release',{}).get('sourceUrl','')])
    overlap=bool(release and release['zone'] in weak)
    emit('G5',bool(weak and release) and overlap,
         {'shooterZone':release['zone'] if release else None,'weakZones':weak,
          'goalieStrengthZones':strong},
         eliminate=bool(weak and release and not overlap),
         source_ids=list(filter(None,[player.get('release',{}).get('sourceUrl'),
             goalie_profile['data'].get('goalieProfileSourceUrl'),goalie_profile['sourceUrl']])))
    dep=player.get('deployment')
    dep_data=evidence_data(dep)
    dep_ok=bool(dep_data and dep_data.get('EV') and dep_data.get('status') in ('PROJECTED','CONFIRMED'))
    # Keep a sourced projected unit only as projected evidence until the team
    # actually confirms it; complete runs with mixed evidence remain MIXED.
    emit('G6',dep_ok,{'deployment':dep_data,'notAllPP1':True,
          'projectedNotPromoted':bool(dep_data and dep_data.get('status')=='PROJECTED')},
         source_ids=[dep.get('sourceUrl','') if dep else ''])
    emit('G7',bool(rec),{'eventLogReconciled':rec,'multiGoalDateOnce':True,'missedGamesExcluded':True},
         source_ids=[p.get('sourceUrl','') for p in (player.get('gameLog'),player.get('mappedGoals')) if p])
    market=player.get('authenticMarket')
    # G8 explicitly neutral when unavailable; never invent market or eliminate a skater.
    emit('G8',True,{'market':evidence_data(market) if receipt(market) else None,
                  'neutralWhenAbsent':not receipt(market),'neverRankingShortcut':True})
    coverage=game.get('coverage',{}).get(attack_team)
    coverage_data=evidence_data(coverage)
    match=bool(coverage_data and release and release['zone'] in coverage_data.get('greenWeakZones',[]))
    zone_concession=(coverage_data.get('zoneConcessions') or {}).get(
        release['zone']) if coverage_data and release else None
    g9_sources=sorted(set(
        ([coverage['sourceUrl']] if receipt(coverage) else [])+
        [u for u in ((coverage_data or {}).get('sourceUrls') or [])
         if isinstance(u,str) and u.startswith('https://')]))
    emit('G9',match,{'shooterZone':release['zone'] if release else None,
                   'greenTarget':coverage_data.get('greenWeakZones',[]) if coverage_data else None,
                   'redAvoid':coverage_data.get('redStrongZones',[]) if coverage_data else None,
                   'coverageSourceType':coverage_data.get('sourceType') if coverage_data else None,
                   'coverageComparison':coverage_data.get('comparison') if coverage_data else None,
                   'zoneConcessionEvidence':zone_concession,
                   'lowShotVolumeNotStrengthEvidence':bool(
                       coverage_data and coverage_data.get(
                           'lowShotVolumeIsNotEvidenceOfDefensiveStrength') is True)},
         eliminate=bool(coverage_data and release and release['zone'] in coverage_data.get('redStrongZones',[])),
         source_ids=g9_sources)
    ownership=player.get('finishOwnership');own=evidence_data(ownership)
    # G10 proves historical OWN goal credit. It cannot certify that this
    # skater will be the recipient rather than an assist provider TONIGHT.
    # The previous hard-coded "notAssistOrFeeder: True" overstated evidence
    # for playmakers and must never appear as proof of tonight's role.
    own_goals=own.get('ownedGoalsInActualAppearances') if own else None
    season_supplement=(own.get('seasonGoalSupplement') or {}).get('data',{}) if own else {}
    season_history=player.get('seasonHistory')
    season_data=evidence_data(season_history) or {}
    season_goal_games=season_data.get('goalScoringGames')
    # An eight-game sample cannot disprove an independently sourced goal
    # earlier in THIS regular season. Official dated player game logs can
    # corroborate OWN season goals shown separately by NHL EDGE shot origin.
    verified_season_goals=bool(
        receipt(season_history)
        and season_data.get('sourceType')=='NHL_OFFICIAL_PLAYER_DATED_REGULAR_SEASON_GAME_LOG'
        and season_data.get('scope')=='OFFICIAL_CURRENT_SEASON_DATED_GAMES_PRIOR_TO_SLATE'
        and str(season_data.get('playerId'))==str(player['id'])
        and type(season_data.get('officialPastSeasonGoals')) is int
        and season_data['officialPastSeasonGoals']>0
        and isinstance(season_goal_games,list) and bool(season_goal_games)
        and all(type(x.get('goals')) is int and x['goals']>0
                and isinstance(x.get('date'),str) and x['date']<str(game['date'])
                and x.get('gameId') for x in season_goal_games)
        and sum(x['goals'] for x in season_goal_games)==
            season_data['officialPastSeasonGoals'])
    sample_goals=bool(rec and type(rec.get('officialGoals')) is int
                      and rec['officialGoals']>0)
    historic_direct=bool(
        receipt(ownership) and own.get('creditedGoalsVerified') is True
        and own.get('recipient') is True and rec and
        (sample_goals or verified_season_goals)
        and (own_goals is None or
             (type(own_goals) is int and own_goals>=0))
        and (not season_supplement or
             type(season_supplement.get('ownedSeasonGoalsFromNhlEdgeShotOrigins')) is int))
    emit('G10',historic_direct,
         {'goalCreditOwned':own,
          'historicalDirectGoalRecipientVerified':historic_direct,
          'historicalDirectGoalRecipientVerificationMethod':
              'RECENT_DATED_PBP_BOXSCORE' if sample_goals else
              'FULL_SEASON_GAME_LOG' if verified_season_goals else None,
          'independentOfficialSeasonGoalHistory':season_data if verified_season_goals else None,
          'directGoalProofIsHistoricalNotTonight':True,
          'futureAssistsVsGoalRecipientUnresolved':True,
          'futureNotAssistOrFeederProven':False,
          'G10_5AndG17MustSeparatelyReviewRecipientCompetition':True},
         eliminate=bool(own and own.get('recipient') is False),
         source_ids=sorted(set(x['sourceUrl'] for x in
             (ownership, season_history if verified_season_goals else None)
             if receipt(x))))
    rivals=[x for x in teammates if str(x['id'])!=str(player['id']) and
            x.get('availability') not in ('OUT','SCRATCHED','INJURED')]
    wins,rows=challenger_proof(player,rivals,weak,
        coverage_data.get('greenWeakZones') if coverage_data else None)
    emit('G10.5',wins is True,
         {'comparisonRows':rows,'allAlternativesScanned':len(rows)==len(rivals),
          'noGuessTransfer':True},
         source_ids=sorted({url for row in rows for url in row.get('sourceUrls',[])
             if url} | ({player['release']['sourceUrl']} if receipt(player.get('release')) else set())))
    shots=player.get('pressure')
    recent_shots=evidence_data(shots,'recentAppearanceShots')
    pressure_valid=isinstance(recent_shots,int) and recent_shots>=0 or (isinstance(recent_shots,list) and bool(recent_shots) and all(isinstance(x,int) and x>=0 for x in recent_shots))
    emit('G11',bool(receipt(shots) and pressure_valid),
         {'recentOwnAttempts':evidence_data(shots,'recentAppearanceShots') if shots else None},
         source_ids=[shots['sourceUrl']] if receipt(shots) else [])
    emit('G12',bool(own and own.get('creditedGoalsVerified') is True and rec is not None),
         {'ownership':own,'officialGoalsReconciled':bool(rec)},
         source_ids=sorted(set(x['sourceUrl'] for x in (
             ownership,player.get('gameLog'),player.get('mappedGoals'),
             player.get('officialGoalTotal')) if receipt(x))))
    jersey=player.get('jersey')
    milestone=player.get('milestone')
    birth=player.get('birthDate') or player.get('birthdate')
    date_value=game.get('date')
    jersey_digits=''.join(ch for ch in str(jersey or '') if ch.isdigit())
    date_digits=''.join(ch for ch in str(date_value or '') if ch.isdigit())
    name=player.get('name')
    # Genuine qualitative name/date/jersey/birth and milestone review,
    # with no formula requirement or fabricated milestone/weights.
    g13={'date':date_value,'name':name,'jersey':jersey,'birthDate':birth,
         'jerseyDateSharedDigits':sorted(set(jersey_digits)&set(date_digits)),
         'verifiedMilestone':evidence_data(milestone) if receipt(milestone) else None,
         'milestoneSourcePresent':receipt(milestone),
         'birthDateAvailable':bool(birth),
         'qualitativeNameDateReview':bool(name and date_value),
         'formula':'none; qualitative only','nonblockingNoInventedWeights':True}
    emit('G13',bool(name and date_value),g13,
         source_ids=[milestone['sourceUrl']] if receipt(milestone) else [])
    who=player.get('whoAnomaly');who_ok=bool(receipt(who) and
        evidence_data(who,'directIndependentRoute') is True and overlap)
    # G14 can neutrally exclude a WHO route, but never invent an anomaly.
    # Checking a sourced release is a real review; constant True was not.
    who_reviewed=bool(receipt(player.get('release')) and release and
                      goalie_profile.get('sourceUrl') and weak)
    unsupported_who=bool(receipt(who) and not who_ok)
    emit('G14',who_reviewed and not unsupported_who,
         {'whoRouteReviewed':who_reviewed,
          'whoAnomalyPhysicallySupported':who_ok,
          'neutralNoWhoAnomaly':not receipt(who),
          'unsupportedWhoEvidence':unsupported_who,
          'noForcedWho':True,
          'whoDetails':evidence_data(who) if who_ok else None},
         source_ids=sorted(set([player['release']['sourceUrl']] if
             receipt(player.get('release')) else []) | set(
             [who['sourceUrl']] if receipt(who) else []) | set(
             [goalie_profile['sourceUrl']] if receipt(goalie_profile) else [])))
    # G15 must be INDEPENDENT of G10's season goal-credit Boolean.
    # Cross-check historical credited goal IDs with a separate official
    # per-origin SHOOTER source. Neither proves tonight's scorer vs feeder.
    # G15 independently compares credited historical season goals from an
    # official dated player log to the skater's OWN NHL EDGE shot-origin
    # finishing observations. No inferred future score or fabricated goal IDs.
    season_release_consistent=bool(
        verified_season_goals and release and
        type(release.get('ownedGoals')) is int
        and release['ownedGoals']<=season_data['officialPastSeasonGoals'])
    finish_corrob=bool(
        own and own.get('recipient') is True and
        receipt(ownership) and rec and (sample_goals or season_release_consistent)
        and receipt(player.get('release')) and release and
        type(release.get('ownedGoals')) is int and release['ownedGoals']>0)
    emit('G15',finish_corrob,
         {'independentHistoricalGoalFinishingEvidence':finish_corrob,
          'goalSourceReconciledToDatedAppearances':bool(rec),
          'separateOfficialShotOriginSource':bool(receipt(player.get('release'))),
          'officialOwnedGoalsInMatchedOrigin':release.get('ownedGoals') if release else None,
          'officialDatedSeasonGoals':season_data.get('officialPastSeasonGoals') if verified_season_goals else None,
          'seasonAndReleaseGoalCreditsConsistent':season_release_consistent if verified_season_goals else None,
          'independentSeasonLogSource':season_history.get('sourceUrl') if verified_season_goals else None,
          'futureGoalVersusAssistRoleNotProven':True,
          'notASecondCopyOfG10RecipientBoolean':True},
         source_ids=sorted(set(x['sourceUrl'] for x in (
             ownership,player.get('release'),player.get('mappedGoals'),
             season_history if verified_season_goals else None)
             if receipt(x))))
    emit('G16',wins is True and len(rows)==len(rivals),
         {'everyOtherActiveTeammate':len(rows),'challengerRows':rows,
          'includesDepthAndDefense':True},
         source_ids=sorted(set(url for row in rows for url in row.get('sourceUrls',[])
             if isinstance(url,str) and url.startswith('https://'))))
    contradiction=player.get('contradictions')
    cdata=evidence_data(contradiction)
    # Having a review OBJECT is not proof that its conflicts were resolved.
    # Source-derived cross-checks must explicitly report no unresolved
    # goalie/role/rival contradiction to pass; never force G17 on placeholder.
    cross_source_resolved=(cdata.get('sourceType')!='DERIVED_CROSS_SOURCE_G17'
                            or cdata.get('unresolved') is False) if cdata else False
    emit('G17',bool(cdata and cdata.get('goalieStrengthReview') is not None and
                     cdata.get('lineupDisagreementReview') is not None and
                     cdata.get('strongestRivalReview') is not None and
                     cross_source_resolved),
         {'goalieBranch':goalie_profile['data'].get('goalieId'),
          'counterevidence':cdata,'retainsConflictingSources':True,
          'sourceDerivedReviewResolved':cross_source_resolved},
         source_ids=[contradiction['sourceUrl']] if receipt(contradiction) else [])
    # Run Phase-1 Step0..Step14 as 16 independent source observations BEFORE
    # G18. Do not copy a master verdict into an overlay record or pretend
    # a missing shift-by-shift source was independently verified.
    overlay=independent_overlay(game,attack_team,player,teammates,goalie_profile,
        release,rec,rows,stage,receipt,evidence_data,gate_record)
    # The path is a RESULT of the physical-source gates, never a preallocated
    # PRIMARY/TRANSFER/WHO slot or an automatic fallback label.
    previous_gates_passed=all(d[g]['disposition']=='PASS' for g in MASTER[:-1])
    route,path_proof=adjudicate_scoring_path(player,teammates,release,
        goalie_profile,coverage,d,rows,who_ok)
    # G18 may never lock a scorer with an insufficient independent overlay.
    overlay_passed=len(overlay)==len(OVERLAY) and all(
        r['disposition']=='PASS' for r in overlay)
    passed=previous_gates_passed and overlay_passed and route is not None
    emit('G18',passed,{
        'candidateEligibleForCrossGameFinal':passed,
        'pathClassificationEvidence':path_proof,
        'classificationOccursAfterAllSourceGates':True,
        'overlayPassedBeforeG18':overlay_passed,
        'notPresetOneOfEach':True},
        source_ids=path_proof['sourceUrls'])
    master_trace=[row['gate'] for row in proof]
    overlay_trace=[row['gate'] for row in overlay]
    if master_trace!=MASTER:
        raise ValueError(f'Master scorer-gate execution order mismatch: {master_trace}')
    if overlay_trace!=OVERLAY:
        raise ValueError(f'Independent overlay execution order mismatch: {overlay_trace}')
    execution_trace=proof[:-1]+overlay+proof[-1:]
    if [row['gate'] for row in execution_trace]!=EXECUTION_ORDER:
        raise ValueError('Combined execution trace does not match the authoritative gate order')
    return {'player':player,'dispositions':d,'complete':passed,'deficientGates':deficient,
            'route':route,'pathEvidence':path_proof,
            'pressure':evidence_data(shots),
            'release':release,'challengers':rows},execution_trace



def verify_complete_matrix(games, records, scan, now=None, selected_directions=None):
    """Patch: 2026-11-05 complete every eligible player and overlay before G18."""
    errors=[]
    now=now or datetime.now(timezone.utc)
    expected_set=set(EXECUTION_ORDER)
    if tuple(OVERLAY)!=tuple(STEP_ORDER):
        errors.append('Phase-1 overlay source order differs from the authoritative mapping')
    for game in games:
        already_started=(game.get('gameState') in ('LIVE','CRIT','OFF','FINAL') or
          (game.get('startUTC') and datetime.fromisoformat(game['startUTC'].replace('Z','+00:00'))<=now))
        if already_started:continue
        direction=(selected_directions or {}).get(str(game['id']))
        if not direction:
            continue  # G0 did not authorize this matchup for skater gates
        active_roster=complete_roster(game,direction['attacker'])
        for person in active_roster:
            pid=str(person['id'])
            candidate_records=[r for r in records
                if r['gameId']==str(game['id']) and r['playerId']==pid]
            actual=[r['gate'] for r in candidate_records]
            if set(actual)!=expected_set:
                missing=[gate for gate in EXECUTION_ORDER if gate not in set(actual)]
                errors.append(f"{game['id']} player {pid} missing gate/overlay records {missing}")
            if actual!=EXECUTION_ORDER:
                errors.append(
                    f"{game['id']} player {pid} wrong gate execution order; "
                    f"expected {EXECUTION_ORDER}, got {actual}")
            for index,entry in enumerate(candidate_records):
                metadata=(entry.get('details') or {})
                if metadata.get('executionIndex')!=index:
                    errors.append(
                        f"{game['id']} player {pid} gate {entry['gate']} "
                        f"has execution index {metadata.get('executionIndex')} not {index}")
            # A filled row is not proof of a gate's own evidence review.
            # Each overlay must have its own pre-G18 source observation.
            for entry in records:
                if (entry['gameId']!=str(game['id']) or entry['playerId']!=pid
                    or entry['gate'] not in OVERLAY):
                    continue
                ev=entry.get('details',{}).get('evidence',{})
                if not (ev.get('independentOverlayEvaluation') is True and
                        ev.get('checkedBeforeG18') is True and
                        ev.get('masterGateVerdictCopied') is False):
                    errors.append(f"{game['id']} player {pid} overlay {entry['gate']} is a copied verdict rather than an independent source check")
        count=sum(1 for r in records if r['gameId']==str(game['id']) and r['gate']=='G0'
                  and r['playerId'].startswith('GOALIE_DIRECTION:'))
        if count!=2:errors.append(f"{game['id']} G0 source directions saved {count} not 2")
    return errors


def g18_source_vector(item):
    """Evidence-complete G18 route-to-goalie match, without invented weights.

    Each finalist already PASSED every G0-G17/overlay gate. For incomparable
    games we separate documented DIRECT OWN goals from the same lane, NHL
    EDGE goalie peer save percentile at that exact lane, independently
    measured opponent team conceded shot share above peer median, then OWN
    shots from the lane. This is an ordered categorical evidence comparison,
    not a model of guaranteed goals, odds, star status, or a weighted score.
    Missing/tied source data cannot be used to break a tie.
    """
    c=item['candidate']
    route=c.get('release') or {}
    g=item.get('targetGoalie') or {}
    gd=g.get('data') or {}
    game=item.get('game') or {}
    zone=route.get('zone')
    if not zone or not isinstance(route.get('ownedGoals'),int):
        return None
    if not isinstance(route.get('attempts'),int) or route['attempts']<=0:
        return None
    if route['ownedGoals']<0 or route['ownedGoals']>route['attempts']:
        return None
    if route['ownedGoals']==0:
        # No G18 direct scorer credit in this exact attack lane. WHO can only
        # enter on a separately documented direct-independent route.
        who=evidence_data(c['player'].get('whoAnomaly'))
        if not who or who.get('directIndependentRoute') is not True:
            return None
    goalie_area=(gd.get('weakZones') or {}).get(zone)
    if not isinstance(goalie_area,dict):
        return None
    cover=(game.get('coverage') or {}).get(item.get('attackTeam'))
    cd=evidence_data(cover)
    if not cd or cd.get('comparison')!='RECENT_OPPONENT_SHOT_ORIGIN_SHARES_AGAINST_PEER_MEDIAN':
        return None
    if zone not in (cd.get('greenWeakZones') or []):
        return None
    defense_zone=(cd.get('zoneConcessions') or {}).get(zone)
    if not isinstance(defense_zone,dict):
        return None
    try:
        pct=Decimal(str(goalie_area['leagueSavePctgPercentile']))
        share=Decimal(str(defense_zone['share']))
        median=Decimal(str(defense_zone['peerMedianShare']))
    except (KeyError,InvalidOperation,TypeError,ValueError):
        return None
    if not (Decimal(0)<=pct<=Decimal(1) and
            Decimal(0)<=median<share<=Decimal(1)):
        return None
    source_urls=list(filter(None,[
        c['player'].get('release',{}).get('sourceUrl'),
        gd.get('goalieProfileSourceUrl'),
        cover.get('sourceUrl'),
        c['player'].get('deployment',{}).get('sourceUrl')]))
    if len(source_urls)!=4 or not all(x.startswith('https://') for x in source_urls):
        return None
    # Explicit procedural separation from already certified G18 finalists.
    # No weighted scoring or made-up prior.
    key=(int(route['ownedGoals']),Decimal(1)-pct,
         share-median,int(route['attempts']))
    proof={
        'gameId':str(game['id']),'playerId':str(c['player']['id']),
        'player':c['player'].get('name'),'attackingTeam':item.get('attackTeam'),
        'goalieId':gd.get('goalieId'),'goalieStarterStatus':gd.get('status'),
        'ownScoringRoute':zone,'directOwnedGoals':int(route['ownedGoals']),
        'ownOnNetShots':int(route['attempts']),
        'goalieLeagueSavePctgPercentile':str(pct),
        'independentDefenseZoneShare':str(share),
        'independentDefensePeerMedian':str(median),
        'sourceUrls':sorted(set(source_urls)),
        'priorityWithoutWeights':['directOwnGoalsFromExactScoringLane',
           'goaliePeerSaveWeaknessInMatchingLane',
           'opponentDefensiveShotShareAboveIndependentPeerMedian',
           'ownShotPressureFromMatchingLane'],
        'method':'G18_VERIFIED_DIRECT_ROUTE_SOURCE_COMPARISON',
        'notAMarketOrChalkScore':True,
    }
    return key,proof


def g18_select_by_evidence(items,required,scope):
    """Return uniquely source-separated recipients; never break exact ties."""
    if len(items)<required:
        return [],[f'G18 {scope}: {len(items)} qualified recipients; {required} required'],[]
    if len(items)==required:
        return items,[],[]
    enriched=[]
    for item in items:
        computed=g18_source_vector(item)
        if computed is None:
            return [],[f'G18 {scope}: comparative evidence missing for one or more fully passing routes'],[]
        key,proof=computed
        enriched.append((key,item,proof))
    enriched.sort(key=lambda row:row[0],reverse=True)
    if enriched[required-1][0]==enriched[required][0]:
        return [],[f'G18 {scope}: verified source evidence tied at decisive slot boundary'],[
            e[2] for e in enriched]
    selected=enriched[:required]
    audit=[{**proof,'selection':'G18_SELECTED' if idx<required else 'G18_SOURCE_SEPARATED',
            'comparedAgainst':len(items)-1}
           for idx,(_,item,proof) in enumerate(enriched)]
    return [entry[1] for entry in selected],[],audit


def cross_game_winners(winners, slate_size):
    """One Core 2/3 only; fully passed candidates from distinct games.

    No arbitrary 'take first three' or popularity/odds shortcut. Source-rich
    candidates may be adjudicated using direct physical-route proof from G18;
    fixture/incomplete source cases still refuse a made-up top three.
    """
    required=2 if slate_size==2 else 3
    if len(winners)<=required:
        return (winners,[]) if len(winners)==required else (
            [],[f'G18 only {len(winners)} fully evidenced games; {required} required'])
    selected,errors,audit=g18_select_by_evidence(winners,required,'cross-game')
    return selected,errors


def build_verified_replacement(con, existing, legs, selected, date, stage):
    """Automatic pre-puck replacement only after stored confirmed-source gate reruns."""
    if stage != 'CONFIRMED':
        return None
    prior = {str(x['gameId']): x for x in existing['current_legs']}
    proposed = {str(x['gameId']): x for x in legs}
    if set(prior) != set(proposed):
        return None
    changed = [gid for gid in prior if str(prior[gid]['playerId']) != str(proposed[gid]['playerId'])]
    if len(changed) != 1:
        return None
    gid = changed[0]
    old, new = prior[gid], proposed[gid]
    item = next((x for x in selected if str(x['game']['id']) == gid), None)
    if not item or str(item['candidate']['player']['id']) != str(new['playerId']):
        return None
    goalie = item['targetGoalie']
    trigger = goalie.get('evidenceId')
    if not trigger or goalie['data']['status'] != 'CONFIRMED':
        return None
    if str(old.get('opposingGoalieId')) == str(new.get('opposingGoalieId')):
        return None
    if not con.execute('SELECT 1 FROM evidence WHERE evidence_id=? AND slate_date=?',
                       (trigger, date)).fetchone():
        return None
    # Prior survivor must fail an actually rerun original physical-route gate.
    failure = con.execute('SELECT disposition,details FROM gates WHERE slate_date=? AND stage=? AND game_id=? AND player_id=? AND gate=?',
                          (date, stage, gid, str(old['playerId']), 'G5')).fetchone()
    if not failure or failure['disposition'] != 'ELIMINATED':
        return None
    candidate = item['candidate']
    rows = candidate['challengers']
    if not rows or any(r['status'] not in ('DEFEATED', 'DIFFERENT_TARGET_LANE',
                                               'SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE') for r in rows):
        return None
    if candidate['dispositions']['G10.5']['disposition'] != 'PASS':
        return None
    if candidate['dispositions']['G17']['disposition'] != 'PASS':
        return None
    g17id = (candidate['player'].get('contradictions') or {}).get('evidenceId')
    if not g17id or not con.execute('SELECT 1 FROM evidence WHERE evidence_id=? AND slate_date=?',
                                   (g17id, date)).fetchone():
        return None
    return {
        'baselineFingerprint': existing['fingerprint'],
        'triggerEvidenceId': trigger,
        'oldValue': {'player': old['player'], 'goalieId': old.get('opposingGoalieId')},
        'newValue': {'player': new['player'], 'goalieId': new.get('opposingGoalieId')},
        'affectedGates': ['G0', 'G3', 'G5'],
        'dependentGates': ['G6', 'G7', 'G9', 'G10', 'G10.5', 'G12', 'G16', 'G17', 'G18'],
        'priorSurvivorFailure': {
            'playerId': old['playerId'], 'failedGate': 'G5',
            'sourceIds': [trigger],
            'detail': 'Prior survivor route no longer fits independently sourced new opposing goalie weakness'
        },
        'g105EveryChallenger': {'comparisonRows': rows, 'candidate': new['playerId']},
        'g17Contradictions': {'sourceIds': [g17id],
                              'review': candidate['dispositions']['G17']['details']},
        'newFingerprint': fingerprint(legs)
    }



def compare_g0_same_origin(direction_a, direction_b):
    """Source-backed same-lane goalie comparison when weak-zone names tie.

    Both opposing goalies have a measured weak area. If one goalie is
    consistently worse in EVERY shared area on BOTH observed goals allowed
    per on-net shot and the NHL's independent league save-percentile ranking,
    that attack direction wins. Never choose based on skaters, fame, odds,
    assumed goal-mouth anatomy, or a fabricated multi-factor weight.
    Return None on disagreement, noncomparable areas, or multiple starters.
    """
    a=direction_a.get('targetGoalies') or []
    b=direction_b.get('targetGoalies') or []
    if len(a)!=1 or len(b)!=1:
        return None
    weak_a=a[0].get('weakZones') or {}
    weak_b=b[0].get('weakZones') or {}
    shared=set(weak_a) & set(weak_b)
    if not shared or set(weak_a)!=set(weak_b):
        return None
    winner=None
    for zone in sorted(shared):
        x=weak_a.get(zone) or {}
        y=weak_b.get(zone) or {}
        fields=('shotsAgainst','goalsAgainst','leagueSavePctgPercentile')
        if any(k not in x or k not in y for k in fields):
            return None
        na,nb=x['shotsAgainst'],y['shotsAgainst']
        ga,gb=x['goalsAgainst'],y['goalsAgainst']
        pa,pb=x['leagueSavePctgPercentile'],y['leagueSavePctgPercentile']
        if any(type(v) not in (int,float) for v in (na,nb,ga,gb,pa,pb)):
            return None
        if na<20 or nb<20 or not (0<=ga<=na and 0<=gb<=nb and 0<=pa<=1 and 0<=pb<=1):
            return None
        # Using fractions avoids floating-point rounding when comparing
        # observed goal rates from different sample sizes.
        higher_goals_a=ga*nb>gb*na
        higher_goals_b=gb*na>ga*nb
        if pa<pb and higher_goals_a:
            orientation='a'
        elif pb<pa and higher_goals_b:
            orientation='b'
        else:
            return None
        if winner is not None and winner!=orientation:
            return None
        winner=orientation
    return direction_a if winner=='a' else direction_b if winner=='b' else None


def compare_g0_different_weak_origins(a,b):
    """When physical weak ORIGINS differ, use NHL's published area peer ranks.

    Before any skaters: two separately sourced starter goalie profiles are
    required. NHL EDGE savePctgPercentile is a PERCENTILE RELATIVE TO
    COMPARABLE GOALIES IN THAT RINK AREA; it is the only common scale
    between distinct shot-origin zones. Lowest percentile = weaker
    published save record vs NHL peers, not biggest raw goals/sample or
    shooting odds. No fabricated weight, no reputation, no skater info.

    Two independent PBP proxy profiles may share the same peer population;
    never compare a PBP-local percentile against a league EDGE percentile.
    Exact ties/noncomparable provenance remain unresolved, not guessed.
    """
    profiles=(a.get('targetGoalies') or [],b.get('targetGoalies') or [])
    if any(len(p)!=1 or p[0].get('profileReviewed') is not True for p in profiles):
        return None
    pa,pb=profiles[0][0],profiles[1][0]
    wa,wb=pa.get('weakZones') or {},pb.get('weakZones') or {}
    if not wa or not wb or set(wa)==set(wb):
        return None  # matched-zone goalie weakness requires direct comparator
    src_a=pa.get('sourceClass')
    src_b=pb.get('sourceClass')
    if src_a!=src_b:
        return None
    # Explicit NHL EDGE (official full-league percentile) or peer-sampled
    # NHL PBP (local percentile), never mixing their meaning.
    if src_a=='DERIVED_RINK_ORIGIN_NOT_ANATOMICAL':
        key='leagueSavePctgPercentile'
        method='NHL_EDGE_SOURCE_PEER_PERCENTILE_CROSS_ORIGIN_G0'
    elif src_a=='INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY':
        key='samplePeerSavePctgPercentile'
        method='NHL_PBP_SAMPLED_PEER_RANK_CROSS_ORIGIN_G0'
    else:
        return None
    def weakest(profile,zones):
        measured=[]
        for zone,metrics in zones.items():
            if not isinstance(metrics,dict):
                return None
            n=metrics.get('shotsAgainst')
            goals=metrics.get('goalsAgainst')
            percentile=metrics.get(key)
            if not (type(n) is int and n>=20 and
                    type(goals) is int and 0<goals<=n and
                    type(percentile) in (int,float) and 0<=percentile<=1):
                return None
            measured.append((percentile,zone,n,goals,metrics))
        if not measured:
            return None
        ordered=sorted(measured,key=lambda row:(row[0],row[1]))
        return ordered[0]
    weakest_a=weakest(pa,wa)
    weakest_b=weakest(pb,wb)
    if weakest_a is None or weakest_b is None:
        return None
    score_a=weakest_a[0];score_b=weakest_b[0]
    if score_a==score_b:
        return None  # no arbitrary alphabetical or star tiebreaker
    chosen,other=(a,b) if score_a<score_b else (b,a)
    win,lose=(weakest_a,weakest_b) if score_a<score_b else (weakest_b,weakest_a)
    return {**chosen,
        'g0SelectionMethod':method,
        'g0SelectedOnlyAfterBothStarterProfiles':True,
        'g0DecisionProof':{
            'reason':'Independent goalie-origin lower published peer save percentile, not game score or skater rank',
            'winnerWeakOrigin':win[1],
            'winnerGoalieOnNetShots':win[2],
            'winnerGoalsAllowedFromOrigin':win[3],
            'winnerGoaliePeerSavePercentile':win[0],
            'oppositeWeakOrigin':lose[1],
            'oppositeGoalieOnNetShots':lose[2],
            'oppositeGoalsAllowedFromOrigin':lose[3],
            'oppositeGoaliePeerSavePercentile':lose[0],
            'samePeerComparatorScope':src_a,
            'noWeightsOrExternalOdds':True,
            'notGloveBlockerFiveHole':True,
            'oppositeDirectionSourceReviewed':True,
            'goalieSourceUrls':[pa.get('goalieProfileSourceUrl') or pa.get('sourceUrl'),
                               pb.get('goalieProfileSourceUrl') or pb.get('sourceUrl')],
        }}


def compare_g0_shared_official_pbp(a,b):
    """G0 only: compare BOTH goalies against ONE historical NHL PBP peer pool.

    The NHL EDGE league percentile and local PBP sample percentiles are NOT
    interchangeable. Only identical, date-locked peer-population IDs and
    exact goalieInNetId PBP historical receipts make this review comparable.
    The chosen attack direction still requires separate skater G3..G18
    confirmation using its independently attached goalie/defense evidence.
    """
    profiles=[x.get('targetGoalies') or [] for x in (a,b)]
    if any(len(x)!=1 for x in profiles):return None
    orig_a,orig_b=profiles[0][0],profiles[1][0]
    pa,pb=orig_a.get('sameCohortPbp'),orig_b.get('sameCohortPbp')
    if not isinstance(pa,dict) or not isinstance(pb,dict):return None
    if not all(isinstance(x.get('sourceUrl'),str)
               and x['sourceUrl'].startswith('https://') for x in (pa,pb)):
        return None
    da,db=pa.get('data') or {},pb.get('data') or {}
    population=da.get('samplePeerPopulationId')
    if not (population and population==db.get('samplePeerPopulationId') and
            da.get('sourceClass')=='INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY' and
            db.get('sourceClass')=='INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY' and
            da.get('peerSampleNeverLeagueEDGEPercentile') is True and
            db.get('peerSampleNeverLeagueEDGEPercentile') is True and
            str(da.get('goalieId'))==str(orig_a.get('goalieId')) and
            str(db.get('goalieId'))==str(orig_b.get('goalieId'))):
        return None
    wa,wb=da.get('weakZones') or {},db.get('weakZones') or {}
    if not wa or not wb:return None
    def qualified(zones):
        return all(isinstance(v,dict) and type(v.get('shotsAgainst')) is int
                   and v['shotsAgainst']>=20
                   and type(v.get('goalsAgainst')) is int
                   and 0<v['goalsAgainst']<=v['shotsAgainst']
                   and type(v.get('samplePeerSavePctgPercentile')) in (int,float)
                   and 0<=v['samplePeerSavePctgPercentile']<=1
                   and v.get('peerComparedSameOrigin') is True
                   and type(v.get('peerGoaliesSampled')) is int
                   and v['peerGoaliesSampled']>=4
                   for v in zones.values())
    if not qualified(wa) or not qualified(wb):return None
    def comparable(original,context,zones):
        g=original['targetGoalies'][0]
        return {**original,'targetGoalies':[{
            **g,'weakZones':zones,
            'sourceClass':'INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY',
            'profileReviewed':True,'goalieProfileSourceUrl':context['sourceUrl']}]}
    aa,bb=comparable(a,pa,wa),comparable(b,pb,wb)
    chosen=compare_g0_different_weak_origins(aa,bb)
    if chosen is None and set(wa)==set(wb):
        # Same-origin zones: demand agreement between the DIRECT on-net
        # goal allowance rate and the peer comparison for EVERY zone.
        # No winner on conflict, exact ties or different peer denominators.
        winner=None
        for zone in sorted(wa):
            x,y=wa[zone],wb[zone]
            na,nb=x['shotsAgainst'],y['shotsAgainst']
            ga,gb=x['goalsAgainst'],y['goalsAgainst']
            ra,rb=x['samplePeerSavePctgPercentile'],y['samplePeerSavePctgPercentile']
            side=('a' if ra<rb and ga*nb>gb*na else
                  'b' if rb<ra and gb*na>ga*nb else None)
            if side is None or (winner is not None and winner!=side):
                return None
            winner=side
        chosen=aa if winner=='a' else bb if winner=='b' else None
    if chosen is None:return None
    original=a if chosen['attacker']==a['attacker'] else b
    proof=chosen.get('g0DecisionProof') or {}
    return {**original,
        'g0SelectionMethod':'SAME_HISTORICAL_OFFICIAL_PBP_GOALIE_PEER_POOL',
        'g0SelectedOnlyAfterBothStarterProfiles':True,
        'g0DecisionProof':{
            **proof,
            'reason':'Same pre-slate official historical goalie PBP peer sample, not mixed with NHL EDGE ranking',
            'samePeerPopulationId':population,
            'goaliePbpSourceUrls':[pa['sourceUrl'],pb['sourceUrl']],
            'sourceCoherentIndependentHistoricalSample':True,
            'opposingGoaliesIndividuallyIdentified':True,
            'noWeightsOrExternalOdds':True,
            'notGloveBlockerFiveHole':True,
            'notGuaranteedTonightGoal':True,
        }}


def compare_g0_consensus_across_starters(a,b):
    """Never choose a PROJECTED starter by picking a convenient candidate.

    If every independently sourced candidate-goalie pairing agrees on one
    attacking side, that side is defensible before starter confirmation.
    Otherwise preserve all branches, record unresolved G0 and do not publish.
    """
    left=a.get('targetGoalies') or []
    right=b.get('targetGoalies') or []
    if not left or not right:return None
    agreed=None;audits=[]
    for goalie_a in left:
        for goalie_b in right:
            if not goalie_a.get('profileReviewed') or not goalie_b.get('profileReviewed'):
                return None
            aa={**a,'targetGoalies':[goalie_a]}
            bb={**b,'targetGoalies':[goalie_b]}
            choice=(compare_g0_same_origin(aa,bb)
                    or compare_g0_different_weak_origins(aa,bb)
                    or compare_g0_shared_official_pbp(aa,bb))
            if choice is None:
                return None
            if agreed is not None and choice['attacker']!=agreed:
                return None
            agreed=choice['attacker']
            audits.append({
                'attacker':choice['attacker'],
                'goalieA':goalie_a.get('goalieId'),
                'goalieB':goalie_b.get('goalieId'),
                'sourceDecisionMethod':choice.get('g0SelectionMethod') or 'MATCHED_ORIGIN_GOAL_RATE_AND_PEER_PERCENTILE',
                'proof':choice.get('g0DecisionProof'),
            })
    if not audits or agreed is None:return None
    original=a if a['attacker']==agreed else b
    return {**original,
        'g0SelectionMethod':'ALL_SOURCE_REVIEWED_STARTER_PAIRS_AGREE',
        'g0SelectedOnlyAfterBothStarterProfiles':True,
        'g0DecisionProof':{
            'allProjectedGoalieCombinationsIndependentlyChecked':len(audits),
            'eachCombinationAttacksSameSide':True,
            'pairwiseReceipts':audits,
            'projectedBranchesNeverSilentlyConfirmed':True,
            'noUnknownGoalieAssumed':True,
            'noWeightsOrArbitraryTieBreaks':True,
        }}


def execute(con, snapshot, date, stage='PROJECTED', now=None):
    now=now or datetime.now(timezone.utc)
    if stage not in ('PROJECTED','CONFIRMED'):raise ValueError('Stage is projected or confirmed')
    games=snapshot.get('games',[])
    if not games:
        msg={'reason':'No official NHL game data provided','stage':stage}
        log_job(con,f'{date}-{stage}',date,stage,'SOURCE_ERROR',msg)
        return {'card':None,'errors':[msg['reason']],'gateRows':0,'scan':[]}
    scan,g0_direction_notes=g0_full_slate(games,stage)
    # Unselected opposing directions are audited, not fatal to the G0-selected side.
    errors=[]
    # Previously activated, source-validated postgame safeguards apply ONLY
    # to later slates. Never re-run or revise a frozen original selection.
    from .postgame_recalibration import active_guards,apply_active_guards
    validated_patch_guards=active_guards(con,date)
    postgame_guard_exclusions=[]
    records=[];qualified=[];all_survivor_receipts=[];pool_size=0
    # Preserve actual G0 goalie-first direction receipts BEFORE skater traces.
    for entry in scan:
        match=next(g for g in games if str(g['id'])==entry['gameId'])
        records.append(gate_record(match,'GOALIE_DIRECTION:'+entry['attacker'], 'G0',
            'PASS' if entry['goalieProfileEvidenced'] else 'NOT_EXECUTED',
            {'attacker':entry['attacker'],'defender':entry['defender'],
             'independentGoalieBranches':entry['targetGoalies'],
             'goalieBeforeSkaters':True},
            [x['sourceUrl'] for x in entry['targetGoalies']]))
    # G0 adjudicates the target goalie and attack side BEFORE the skater pool.
    # Independent zone evidence must distinguish directions; no popularity,
    # market, arbitrary weights, or alphabetic tiebreaks.
    selected_directions={}
    for match in games:
        options=[x for x in scan if x['gameId']==str(match['id'])]
        # HARD G0 DEPENDENCY: both source-backed starter profiles must be
        # observed, even when one is independently measured as stronger/no
        # weakness. The old len(options)==1 route selected a team SOLELY
        # because the opposing goalie had no data, never an evidence decision.
        if len(options)!=2 or not all(o['goalieProfileEvidenced'] for o in options):
            errors.append(f"{match['id']} G0 both attack directions REQUIRE independent goalie profiles; one-sided source presence is NOT a selection rule")
            continue
        def weakness_vector(direction):
            profiles=direction['targetGoalies']
            if len(profiles)!=1:
                return None
            zones=profiles[0]['weakZones']
            if not isinstance(zones,dict):
                return None
            # The goalie may have NO weak origins in a separately observed,
            # sufficient NHL EDGE/PBP sample: that is source-backed negative
            # evidence, not an unresolved or assumed weakness.
            if not zones and not profiles[0].get('profileReviewed'):
                return None
            # G0 compares evidence-backed goalie-origin lanes. Never
            # infer glove/blocker/five-hole from these rink coordinates.
            return set(zones)
        left,right=(weakness_vector(x) for x in options)
        if left is not None and right is not None and left!=right:
            if left>right:
                selected_directions[str(match['id'])]=options[0]
                continue
            if right>left:
                selected_directions[str(match['id'])]=options[1]
                continue
        # Source-based comparison covers the important case where both
        # goalies are weak from the SAME area (set equality). More exposed
        # goalie must be worse by BOTH empirical goal rate and published
        # league save-percentile; otherwise keep G0 unresolved.
        comparative=compare_g0_same_origin(options[0],options[1])
        if comparative is not None:
            selected_directions[str(match['id'])]={**comparative,
                'g0SelectionMethod':'MATCHED_ORIGIN_DIRECT_GOAL_RATE_AND_PEER_PERCENTILE',
                'g0SelectedOnlyAfterBothStarterProfiles':True}
            continue
        # Different goalie weaknesses are not unreviewed/uncomparable merely
        # because they come from different named zones. Compare the league's
        # normalized SOURCE percentile on each goalie's independently
        # demonstrated worst vulnerable origin, while the full opposing
        # profiles stay on record and every skater later passes G4/G5/G9.
        distinct=compare_g0_different_weak_origins(options[0],options[1])
        if distinct is not None:
            selected_directions[str(match['id'])]=distinct
            continue
        # Both goalie directions and every projected starter must be
        # source-reviewed BEFORE advancing players. A common official PBP
        # peer cohort can resolve mixed NHL EDGE/PBP evidence WITHOUT ever
        # comparing their incompatible percentile populations directly.
        consensus=compare_g0_consensus_across_starters(options[0],options[1])
        if consensus is not None:
            selected_directions[str(match['id'])]=consensus
            continue
        errors.append(f"{match['id']} G0 neither a shared official goalie-peer comparison nor unanimous projected-starter evidence distinguished the attacking direction")
    # A G0 failure MUST NOT silently short-circuit all 36 source checks.
    # Investigate each available goalie branch against each official skater
    # on BOTH sides, while retaining a FAILED G0 and forbidding selection.
    unresolved_branch_analyses=[]
    unresolved_unique_pool=0
    for match in games:
        gid=str(match['id'])
        if gid in selected_directions:
            continue
        started=match.get('gameState') in ('LIVE','CRIT','OFF','FINAL') or (
            match.get('startUTC') and
            datetime.fromisoformat(match['startUTC'].replace('Z','+00:00'))<=now)
        if started:
            continue
        for attacker,defender in ((match['away'],match['home']),
                                  (match['home'],match['away'])):
            players=complete_roster(match,attacker)
            unresolved_unique_pool+=len(players)
            branches=all_goalie_branches(match,stage).get(defender,[])
            for branch in branches:
                goalie_id=str(branch['data'].get('goalieId') or 'UNKNOWN')
                for player in players:
                    scoped=release_matched_to_g0_target(
                        player,branch,match.get('coverage',{}).get(attacker))
                    # No _g0SelectedDirection: these are NOT proposed Core
                    # paths. Every gate is physically checked with the real
                    # source branch, but G0 and G18 must remain nonpassing.
                    candidate,trace=evaluate_skater(
                        match,attacker,scoped,players,branch,stage)
                    if candidate['dispositions']['G0']['disposition']=='PASS' or candidate['complete']:
                        raise ValueError('G0 research cannot become a certified scorer')
                    research_id=f'G0_RESEARCH:{attacker}:{goalie_id}:{player["id"]}'
                    for row in trace:
                        row['playerId']=research_id
                        row['details']['g0ResearchOnly']=True
                        row['details']['actualOfficialPlayerId']=str(player['id'])
                        row['details']['researchGoalieId']=goalie_id
                        row['details']['g0DirectionNotDecided']=True
                        row['details']['cannotBeSelectedOrPublished']=True
                    if [row['gate'] for row in trace]!=EXECUTION_ORDER:
                        raise ValueError('G0 research skipped master or overlay gates')
                    records.extend(trace)
                    unresolved_branch_analyses.append({
                        'gameId':gid,'attacker':attacker,'goalieId':goalie_id,
                        'playerId':str(player['id']),
                        'masterAndOverlayChecks':len(trace),
                        'g0Disposition':'NOT_EXECUTED',
                        'cannotEnterG18Card':True})
    # Missing G0 direction remains a hard selection blocker. It is NOT
    # permission to skip the rest of the physical-evidence investigation.
    for match in games:
        is_started=match.get('gameState') in ('LIVE','CRIT','OFF','FINAL') or (
            match.get('startUTC') and datetime.fromisoformat(match['startUTC'].replace('Z','+00:00')) <= now)
        if is_started:
            # Not eligible for new selection; frozen cards remain in storage.
            continue
        direction=selected_directions.get(str(match['id']))
        if direction is None:
            continue
        team=direction['attacker']
        opponent=direction['defender']
        players=complete_roster(match,team)
        pool_size+=len(players)
        if not players:
            errors.append(f"{match['id']} G2 complete roster missing for G0-selected attack side {team}")
            continue
        for p in players:
            if not p.get('release'):
                p['archetypeEvidence']='NOT_ACQUIRED'
        branches=all_goalie_branches(match,stage).get(opponent,[])
        if not branches:
            errors.append(f"{match['id']} G0-selected opposing goalie branch missing for {opponent}")
            continue
        all_per_game=[]
        for branch in branches:
            for player in players:
                scoped=release_matched_to_g0_target(player,branch,match.get('coverage',{}).get(team))
                # Bind the G0 direction receipt to every skater checked after
                # goalie-first selection; never infer direction from a PASS.
                scoped_game={**match,'_g0SelectedDirection':direction}
                result,traces=evaluate_skater(scoped_game,team,scoped,players,branch,stage)
                result,traces,guard_rejections=apply_active_guards(
                    result,traces,validated_patch_guards)
                if guard_rejections:
                    postgame_guard_exclusions.append({
                        'gameId':str(match['id']),'playerId':str(player['id']),
                        'rejections':guard_rejections})
                records+=traces
                if result['complete']:
                    all_per_game.append({'game':match,'attackTeam':team,'targetGoalie':branch,
                                         'candidate':result})
                    z=result['release']['zone']
                    gweak=branch['data'].get('weakZones') or {}
                    defense=match.get('coverage',{}).get(team) or {}
                    coverage=(defense.get('data') or {}).get('zoneConcessions') or {}
                    own=result['player']
                    all_survivor_receipts.append({
                        'gameId':str(match['id']),
                        'matchup':match['away']+'@'+match['home'],
                        'gameStartUTC':match.get('startUTC'),
                        'attackTeam':team,'opponentTeam':opponent,
                        'playerId':str(own['id']),'player':own.get('name'),
                        'routeLabel':result['route'],
                        'pathClassificationEvidence':result.get('pathEvidence',{}),
                        'ownRouteZone':z,
                        'ownedGoals':result['release']['ownedGoals'],
                        'ownShotsOnGoal':result['release']['attempts'],
                        'routeSource':(own.get('release') or {}).get('sourceUrl'),
                        'goalieId':branch['data'].get('goalieId'),
                        'goalieStatus':branch['data'].get('status'),
                        'goalieSourceUrl':branch['data'].get('goalieProfileSourceUrl'),
                        'goalieObservedZoneStats':gweak.get(z),
                        'independentOpponentDefense':coverage.get(z),
                        'defenseSourceUrl':defense.get('sourceUrl'),
                        'deployment':(own.get('deployment') or {}).get('data'),
                        'deploymentSourceUrl':(own.get('deployment') or {}).get('sourceUrl'),
                        'nonRankingDiagnosticOnly':True,
                    })
        if len(all_per_game)==1:
            qualified.append(all_per_game[0])
        elif len(all_per_game)>1:
            winner,comparison_errors,review=g18_select_by_evidence(
                all_per_game,1,'one-survivor-game-'+str(match['id']))
            if winner:
                qualified.extend(winner)
            else:
                errors += comparison_errors or [
                    f"{match['id']} G18 multiple source-unseparated recipients"]
    pool_size+=unresolved_unique_pool
    save_gates(con,date,stage,records)
    chosen,selection_errors=cross_game_winners(qualified,len(games))
    selection_errors += verify_complete_matrix(games,records,scan,now,selected_directions)
    # A game that has already started cannot be newly picked. Such a game is
    # excluded from the candidate pool above, but does not veto later games.
    # G0 surveys both directions; the losing direction does not have to
    # pass G0 or the skater matrix. Only selected attack directions advance.
    errors+=selection_errors
    card=None
    if chosen and not selection_errors:
        legs=[]
        for x in chosen:
            p=x['candidate']['player'];g=x['game'];goalie=x['targetGoalie']
            legs.append({'gameId':str(g['id']),'playerId':str(p['id']),
                        'player':p.get('name',str(p['id'])),'path':x['candidate']['route'],
                        'matchup':g['away']+'@'+g['home'],'startUTC':g['startUTC'],
                        'gameState':g.get('gameState','FUT'),
                        'opposingGoalieId':goalie['data']['goalieId'],
                        'sourceIds':sorted({goalie['sourceUrl'],p['release']['sourceUrl'],
                                            p['deployment']['sourceUrl']}),
                        'directRoute':x['candidate']['release']['archetype']+' / '+x['candidate']['release']['zone']})
        # save_card enforces one slate identity, puck-drop freeze, and full replacement audit.
        try:
            existing=get_card(con,date)
            audit=None
            if existing and existing['fingerprint']!=fingerprint(legs):
                audit=build_verified_replacement(con,existing,legs,chosen,date,stage)
                if not audit:
                    raise ValueError('Different scorer candidates did not satisfy a verified old-to-new source, prior-player failure, and G10.5/G17 replacement audit; the original card is preserved.')
            evidence_stage=stage
            if stage=='CONFIRMED' and any(
                x['targetGoalie']['data'].get('status')!='CONFIRMED' or
                (x['candidate']['player'].get('deployment') or {}).get('data',{}).get('status')!='CONFIRMED'
                for x in chosen):
                evidence_stage='MIXED'
            card=save_card(con,date,evidence_stage,legs,len(games),audit=audit,now=now)
        except ValueError as e:errors.append(str(e))
    # Additional matchups are allowed to have unseparated goalies once
    # three distinct, source-qualified game recipients have been saved.
    # Such a game is still recorded as rejected by G0. It is NOT a failure
    # of a separately certified and preserved Core 3.
    nonselected_game_notes=[]
    if card:
        selected_game_ids={str(x['gameId']) for x in card['current_legs']}
        remaining=[]
        for message in errors:
            if (isinstance(message,str) and
                ' G0 attack sides not physically separated by certified goalie weaknesses' in message
                and message.split(' ',1)[0] not in selected_game_ids):
                nonselected_game_notes.append(message)
            elif (isinstance(message,str) and
                  (' G0 no independently evidenced goalie target' in message or
                   ' G0 both attack directions REQUIRE independent goalie profiles' in message)
                  and message.split(' ',1)[0] not in selected_game_ids):
                nonselected_game_notes.append(message)
            else:
                remaining.append(message)
        errors=remaining
    gaps=defaultdict(int)
    for rec in records:
        if rec['disposition']=='NOT_EXECUTED':gaps[rec['gate']]+=1
    result={'card':card,'date':date,'stage':stage,'games':len(games),
            'g0TwoGoalieDirectionDecisions':{
                gid:{'attackingTeam':d['attacker'],'targetGoalieTeam':d['defender'],
                     'goalieSourceMethod':d.get('g0SelectionMethod') or 'SOURCE_WEAK_ZONE_SET_CONTAINMENT',
                     'decisionEvidence':d.get('g0DecisionProof'),
                     'bothGoaliesReviewedFirst':True,
                     'isAnatomicalWeaknessClaim':False}
                for gid,d in selected_directions.items()},
            'g0Directions':len(scan),'g0Complete':sum(bool(x['goalieProfileEvidenced']) for x in scan),
            'eligibleSkaterRows':pool_size,'gateRows':len(records),'missingByGate':dict(gaps),
            'unresolvedG0ResearchBranchCount':len(unresolved_branch_analyses),
            'unresolvedG0PlayerSourceChecks':sum(x['masterAndOverlayChecks']
                    for x in unresolved_branch_analyses),
            'unresolvedG0ResearchDoesNotSelect':True,
            'unresolvedG0ResearchExamples':unresolved_branch_analyses[:20],
            'uniqueGameSurvivors':len(qualified),
            'allG18QualifiedSurvivors':all_survivor_receipts,
            'nonselectedGameResearchNotes':nonselected_game_notes,
            'nonselectedGameResearchNeverReplacesLockedCore':True,
            'activePostgameGuards':validated_patch_guards,
            'futureGateGuardRejections':postgame_guard_exclusions,
            'retroactiveCardMutation':False,
            'errors':errors,'scan':scan}
    log_job(con,f'{date}-{stage}',date,stage,'COMPLETE' if card else 'INPUT_INCOMPLETE',
            {k:v for k,v in result.items() if k not in ('card','scan')})
    return result