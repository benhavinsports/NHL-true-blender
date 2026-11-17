"""Evidence-driven NHL G0..G18 executor. No favorites, arbitrary weights or proxy goalies.

Input is a source-annotated game snapshot produced by collectors, not a list of picks.
Output is an immutable gate record for every surveyed direction and skater.
Only the uniquely defensible, fully evidenced survivors can be published.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from .storage import save_card, save_gates, log_job, get_card, fingerprint
from .overlay_checks import independent_overlay, STEP_ORDER
from .rival_scope import g17_resolved_without_eliminated_rivals
from .semantic_certification import audit_gate
from .route_continuation import observed_own_shot_appearances, observed_dated_recurrence

# The user's 18 numbered scorer gates remain individually named and ordered.
# G10.5 is the mandatory half-step between G10 and G11. G0 is the
# separate goalie-first direction decision, not a substitute for scorer gates.
SCORER_GATE_ORDER = ([f'G{i}' for i in range(1,11)] +
                     ['G10.5'] + [f'G{i}' for i in range(11,19)])
MASTER = ['G0'] + SCORER_GATE_ORDER
OVERLAY = ([f'Step{i}' for i in range(11)] + ['Step10.5'] +
           [f'Step{i}' for i in range(11,15)])
# The historical Step descriptions are functions WITHIN the original gates,
# never a second gate sequence, an independent pass, or 16 more selections.
# Keep their observation names solely to preserve evidence provenance.
STEP_OWNER = {'Step0':'G0','Step1':'G2','Step2':'G1','Step3':'G5',
              'Step4':'G7','Step5':'G4','Step6':'G6','Step7':'G4',
              'Step8':'G9','Step9':'G11','Step10':'G5',
              'Step10.5':'G10.5','Step11':'G14','Step12':'G16',
              'Step13':'G13','Step14':'G17'}
STEPS_BY_GATE = {gate:[step for step in OVERLAY if STEP_OWNER[step]==gate]
                 for gate in MASTER}
EXECUTION_ORDER = MASTER[:]
if EXECUTION_ORDER != ['G0'] + SCORER_GATE_ORDER or EXECUTION_ORDER[-1] != 'G18':
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
        else:
            # A dated first-hand morning-skate FIRST-GOALIE-OFF report is
            # direct rink observation, stronger evidence than an independent
            # algorithmic probability prediction or a generic roster-first
            # ordering. Never call this CONFIRMED or use a secondhand
            # report from another slate date. If eyewitness observations
            # conflict with each other, preserve every branch.
            first_off=[b for b in branches if
                b['data'].get('status')=='EXPECTED' and
                b['data'].get('datedEyewitnessMorningSkateFirstOff') is True and
                b['data'].get('sourceReportDate')==game.get('date') and
                bool(b['data'].get('morningSkateSourceUrls'))]
            first_off_ids={str(b['data'].get('goalieId')) for b in first_off}
            if len(first_off_ids)==1:
                # The same goalie ID may carry multiple dated independent
                # reports; no manual selection of a source or goalie.
                reported=next(iter(first_off_ids))
                branches=[b for b in branches if str(b['data'].get('goalieId'))==reported]
            else:
                # Without independent FIRST-OFF evidence, the original
                # conservative rule is unchanged: disagreeing projected
                # sources leave ALL eligible starter branches intact.
                preferred=[b for b in branches if
                           b['data'].get('projectedPreferred') is True]
                if len({str(b['data'].get('goalieId')) for b in preferred})==1:
                    branches=preferred
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



def g0_source_coherent_scorer_goalie(game, direction, starter):
    """Carry the G0 deciding *source*, not an unrelated empty EDGE profile,
    into the original per-skater G0/G3/G5 route checks.

    A same-cohort official NHL PBP goalie comparison is sometimes the only
    measured source that G0 used to pick the attack side (e.g. VGK's starter
    has no separately qualified NHL EDGE weak area). Previously the source
    DID decide G0, yet skater evaluation silently reverted to the old empty
    EDGE weakZones and marked every player G0 NOT_EXECUTED. This function
    may NOT create a G0 direction or convert any estimated starter to
    CONFIRMED; it only carries the *same actual historical evidence* through
    the original gates, with the dated goalie ID, population, and source URL.
    """
    if not (isinstance(direction,dict) and
            direction.get('g0SelectionMethod') ==
                'ALL_SOURCE_REVIEWED_STARTER_PAIRS_AGREE' and
            direction.get('attacker') in (game['away'],game['home']) and
            starter and isinstance(starter.get('data'),dict)):
        return starter
    base=starter['data']
    if base.get('weakZones'):
        return starter  # Never replace an already source-qualified NHL EDGE lane
    gid=str(base.get('goalieId') or '')
    receipts=(direction.get('g0DecisionProof') or {}).get('pairwiseReceipts') or []
    if not receipts or not all(
        rec.get('attacker')==direction['attacker'] and
        rec.get('sourceDecisionMethod')=='SAME_HISTORICAL_OFFICIAL_PBP_GOALIE_PEER_POOL' and
        gid in (str(rec.get('goalieA')),str(rec.get('goalieB'))) and
        (rec.get('proof') or {}).get('sourceCoherentIndependentHistoricalSample') is True
        for rec in receipts):
        return starter
    populations={str((rec.get('proof') or {}).get('samePeerPopulationId') or '') for rec in receipts}
    if len(populations)!=1 or not next(iter(populations)):
        return starter
    peer=(game.get('goaliePeerContexts') or {}).get(gid)
    if not receipt(peer):
        return starter
    data=peer.get('data') or {}
    weak=data.get('weakZones') or {}
    if not (
        str(data.get('goalieId'))==gid and
        data.get('samplePeerPopulationId') in populations and
        data.get('sourceClass')=='INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY' and
        data.get('peerSampleNeverLeagueEDGEPercentile') is True and
        isinstance(weak,dict) and bool(weak) and
        isinstance(data.get('sample'),dict) and
        isinstance(data.get('counterevidence'),dict) and
        type(data.get('fullySourceComparedAreas')) is int and
        data['fullySourceComparedAreas']>0 and
        all(type(v.get('shotsAgainst')) is int and v['shotsAgainst']>=20 and
            type(v.get('goalsAgainst')) is int and 0<v['goalsAgainst']<=v['shotsAgainst'] and
            v.get('peerComparedSameOrigin') is True and
            type(v.get('peerGoaliesSampled')) is int and v['peerGoaliesSampled']>=4
            for v in weak.values())):
        return starter
    # Keep the original starter identity/status. Every derived vulnerability
    # comes as one coherent official PBP peer source, never a hybrid with EDGE.
    pdata={**base,
        'weakZones':weak,
        'strengthZones':data.get('strengthZones') or {},
        'sample':data['sample'],
        'counterevidence':data['counterevidence'],
        'fullySourceComparedAreas':data['fullySourceComparedAreas'],
        'sourceReviewed':True,
        'sourceClass':data['sourceClass'],
        'sourceType':data.get('sourceType'),
        'evidenceScope':'INDEPENDENT_HISTORICAL_OFFICIAL_PBP_RINK_ORIGIN',
        'goalieProfileSourceUrl':peer['sourceUrl'],
        'goalieProfileObservedAt':peer['observedAt'],
        'goalieProfileEvidenceId':peer.get('evidenceId'),
        'samePeerPopulationId':data['samplePeerPopulationId'],
        'sourceCoherentG0ToG5':True,
        'notGoalMouthAnatomy':True}
    return {**starter,'data':pdata}

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


def independently_dated_origin_route(player,zone):
    """A positive NHL PBP shooter-origin observation for G10.5 tied recipients."""
    wrapper=player.get("recentOrigin")
    if not receipt(wrapper):
        return None
    data=wrapper.get("data") or {}
    if (data.get("sourceType")!="OFFICIAL_NHL_DATED_PBP_SHOOTER_ORIGIN"
        or data.get("scope")!="RECENT_PRE_SLATE_TARGET_CLUB_GAMES_ONLY"
        or data.get("rinkBinsApproximateNotNhlEdgePolygons") is not True
        or data.get("historicalOwnGoalCreditOnly") is not True):
        return None
    area=(data.get("zoneCounts") or {}).get(zone)
    if not isinstance(area,dict):
        return None
    onnet=area.get("shotsOnGoal");goals=area.get("ownedGoals")
    if not (type(onnet) is int and onnet>0 and type(goals) is int
            and 0<=goals<=onnet and isinstance(area.get("sourceUrls"),list)
            and len(area["sourceUrls"])>0):
        return None
    return {"ownedGoals":goals,"shotsOnGoal":onnet,
            "sourceUrls":area["sourceUrls"],
            "scope":"SOURCE_DATED_PBP_APPROXIMATE_RINK_ORIGIN",
            "notAnNhlEdgeAreaPolygon":True}


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
        recent_tie_proof=None
        if candidate_direct==rival_direct:
            # A season NHL EDGE tie is not permission to choose chalk or
            # arbitrarily move G10.5. Research BOTH players' independent,
            # dated, directly credited NHL PBP shots from their own routes.
            # Positive evidence must exist for BOTH, using the same source
            # method. Missing/identical observations stay unresolved.
            own_recent=independently_dated_origin_route(candidate,base["zone"])
            rival_recent=independently_dated_origin_route(rival,target["zone"])
            if own_recent and rival_recent:
                pair_a=(own_recent["ownedGoals"],own_recent["shotsOnGoal"])
                pair_b=(rival_recent["ownedGoals"],rival_recent["shotsOnGoal"])
                recent_tie_proof={
                    "method":"INDEPENDENT_DATED_OFFICIAL_SHOOTER_PBP_ORIGIN",
                    "own":own_recent,"rival":rival_recent,
                    "sameRecentSampleMethod":True,
                    "seasonGoalAndShotTieReviewed":True,
                    "notAnatomicalPlacement":True}
                if pair_a!=pair_b:
                    dominates=pair_a>pair_b
                    defeated_by=pair_b>pair_a
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
            'sourceUrls':sorted(set(
                [candidate['release']['sourceUrl'],wrapper['sourceUrl']] +
                (recent_tie_proof['own']['sourceUrls']+
                 recent_tie_proof['rival']['sourceUrls']
                 if recent_tie_proof else []))),
            'independentRecentTieReview':recent_tie_proof,
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
            # G10.5 can use shot volume to separate competing shooters,
            # but it cannot claim a direct PRIMARY goal recipient was
            # displaced by a TRANSFER when their observed OWN goals tie.
            # Historical on-net shot pressure is not credited goal ownership.
            base_direct['ownedGoals']>rival_direct['ownedGoals']):
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
    # Owner rule (2026-11-17): a player whose goalie-first G0 route moved
    # him OFF his usual lane into the goalie's weak lane, where he owns
    # goals and beat every same-lane teammate at G10.5/G16, is a TRANSFER.
    # No displaced usual owner of that lane is required. It still needs
    # every direct gate (route_direct), so nothing is relaxed elsewhere.
    off_lane_transfer=bool(changed_lane and route_direct)
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
        (confirmed_displacement or derived_displacement or off_lane_transfer))
    if path_contradiction:
        path=None
        rationale='Two different sourced physical paths remain unseparated; no preferred label assigned'
    elif physical_anomaly:
        path='WHO'
        rationale='Sourced independent anomaly scoring mechanism survived G14, goalie route and full gates'
    elif route_direct and (confirmed_displacement or derived_displacement):
        path='TRANSFER'
        rationale='Own secondary scoring route defeated independently sourced same-lane original PRIMARY recipient under G10.5'
    elif off_lane_transfer:
        path='TRANSFER'
        rationale=('Goalie-first G0 moved this player off his usual lane into the goalie weak lane, '
                   'where he owns goals and beat every same-lane teammate under G10.5/G16')
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
        'offUsualLaneTransferIntoGoalieWeakLane':off_lane_transfer,
        'G14IndependentWhoAnomalyVerified':physical_anomaly,
        'competingWHOandTRANSFERPathsUnseparated':path_contradiction,
        'whoPhysicalMechanism':who_data.get('mechanism') if physical_anomaly else None,
        'sourceUrls':sources,
        'selectionIndependentOfLabel':True,
        'pathQuotaApplied':False,
        'fallbackToPrimary':False,
        'unknownIsNotAPath':True,
    }



def stopped_before_g10_5(results):
    """Map playerId -> first non-PASS gate before G10.5 from a first pass.

    G0-G10 are individual checks that never consult teammates, so their
    dispositions are identical in both passes; only G10.5/G16 change.
    """
    before=MASTER[:MASTER.index('G10.5')]
    out={}
    for result in results:
        d=result['dispositions']
        stop=next((g for g in before if (d.get(g) or {}).get('disposition')!='PASS'),None)
        if stop is not None:
            out[str(result['player']['id'])]=f"{stop}:{d[stop]['disposition']}"
    return out


def _finish_pool(games,game_pool,card,g16_receipt):
    """Every slate game in schedule order, marked with its Core outcome."""
    core={(str(x['gameId']),str(x['playerId'])) for x in (card or {}).get('current_legs') or []}
    g16={str(f.get('playerId')):f for f in (g16_receipt or {}).get('finalists') or []}
    out=[]
    for match in games:
        e=dict(game_pool.get(str(match['id'])) or {'gameId':str(match['id']),
               'matchup':match['away']+'@'+match['home'],'status':'NOT_EVALUATED'})
        sv=e.get('survivor') or {}
        e['inCore']=(e['gameId'],str(sv.get('playerId')))in core if sv else False
        if sv and str(sv.get('playerId')) in g16:
            f=g16[str(sv['playerId'])]
            e['g16Decision']=f.get('g16Decision'); e['g16DominatedBy']=f.get('dominatedBy')
        e['poolIsDiagnosticAndNeverSelects']=True
        out.append(e)
    return out


def evaluate_skater(game, attack_team, player, teammates, goalie_profile, stage,
                    stopped_before_g10_5=None, defer_g18=False):
    d={}; proof=[]; deficient=[]; eliminated=False; first_elimination_gate=None
    # Teammates who passed G0-G10 (see stopped_before_g10_5). Only these are
    # meaningful G10.5/G16 challengers, for the master gate and its overlay.
    stopped=dict(stopped_before_g10_5 or {})
    # Only source-verified ELIMINATED teammates leave the challenger pool.
    # Unresolved (NOT_EXECUTED) teammates are still compared: they cannot
    # eliminate anyone, but while unresolved they keep the decision open.
    eliminated_before={k for k,v in stopped.items() if v.endswith(':ELIMINATED')}
    unresolved_before={k for k,v in stopped.items() if not v.endswith(':ELIMINATED')}
    live_teammates=[x for x in teammates if str(x['id'])==str(player['id'])
                    or str(x['id']) not in eliminated_before]
    weak=goalie_profile['data'].get('weakZones',{})
    strong=goalie_profile['data'].get('strengthZones',{})
    release=player_releases(player)
    rec=reconcile_logs(player)
    # Immutable source observations; G7, G11 and overlays decide independently.
    shot_review=observed_own_shot_appearances(evidence_data(player.get('pressure')) or {})
    dated_recurrence=observed_dated_recurrence(rec,shot_review)
    position=player.get('position')
    # G10.5 is the first gate allowed to adjudicate same-lane recipients.
    # Earlier gates must not silently precompute or preselect a winner.
    rows=[]
    wins=None
    overlay=[]
    execution_trace=[]
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
        # Evaluate only the source observations owned by this gate, now,
        # before recording its authoritative disposition.
        # Step-named functions run as source checks inside their owning gate.
        # They do NOT write independent gate rows or create a 36-gate pipeline.
        # An observation is an intermediate value, not a stored gate receipt.
        def observation_record(_game,_player,step,status,evidence,ids):
            return {'gate':step,'disposition':status,
                    'details':{'evidence':evidence,'sourceIds':list(ids)}}
        observations=(independent_overlay(
            game,attack_team,player,live_teammates,goalie_profile,release,rec,
            rows,stage,receipt,evidence_data,observation_record,
            only_steps=set(STEPS_BY_GATE[g]),
            eliminated_rivals=eliminated_before) if STEPS_BY_GATE[g] else [])
        overlay.extend(observations)
        if observations:
            function_evidence=[{
                'step':item['gate'],'disposition':item['disposition'],
                'sourceIds':item['details'].get('sourceIds',[]),
                'evidence':item['details'].get('evidence',{})}
                for item in observations]
            content={**content,'originalFunctionEvidence':function_evidence,
                     # Historical consumers can read the same nested evidence.
                     'independentOverlayEvidence':function_evidence}
            mandatory=[item for item in observations
                       if item['disposition']!='PASS'
                       and item['details'].get('evidence',{}).get('nonblocking') is not True]
            for item in mandatory:
                deficient.append(g+':'+item['gate'])
            if mandatory and disp=='PASS':
                # The original function is part of THIS gate's result, not
                # another veto stage operating after the master sequence.
                disp=('ELIMINATED' if any(
                    x['disposition']=='ELIMINATED' for x in mandatory)
                    else 'NOT_EXECUTED')
                content['ownFunctionDispositions']={
                    x['gate']:x['disposition'] for x in mandatory}
                if disp=='ELIMINATED':
                    eliminated=True
                    if first_elimination_gate is None:first_elimination_gate=g
        d[g]={'disposition':disp,'details':content}
        record=gate_record(game,player['id'],g,disp,content,list(source_ids))
        proof.append(record)
        execution_trace.append(record)
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
    dep_ok=bool(dep_data and dep_data.get('EV') and dep_data.get('status') in ('PROJECTED','CONFIRMED') and not player.get('deploymentConflict'))
    # Keep a sourced projected unit only as projected evidence until the team
    # actually confirms it; complete runs with mixed evidence remain MIXED.
    emit('G6',dep_ok,{'deployment':dep_data,'notAllPP1':True,
          'projectedNotPromoted':bool(dep_data and dep_data.get('status')=='PROJECTED'),
          'deploymentConflict':bool(player.get('deploymentConflict'))},
         source_ids=[dep.get('sourceUrl','') if dep else ''])
    # G7: two observed dates are the minimal meaning of recurrence. Compare
    # credited goals OR dated shooter-owned attempts, not mere log existence.
    emit('G7',dated_recurrence['datedScoringOrShotRecurrence'],
         {'eventLogReconciled':rec,'multiGoalDateOnce':True,
          'missedGamesExcluded':True,**dated_recurrence},
         source_ids=[p['sourceUrl'] for p in (
             player.get('gameLog'),player.get('mappedGoals'),player.get('pressure'))
             if receipt(p)],
         # Complete dated counterevidence is an elimination, not "data missing".
         eliminate=bool(rec and shot_review['valid']
                        and shot_review['datedAppearanceAlignmentVerified']
                        and not dated_recurrence['datedScoringOrShotRecurrence']))
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
    # G10.5/G16 compare against MEANINGFUL challengers only. A teammate
    # already ELIMINATED before G10.5 cannot own a route (G18 never reopens
    # eliminated candidates). An unresolved teammate is still compared but
    # cannot eliminate; it can only keep the decision NOT_EXECUTED.
    rivals=[x for x in live_teammates if str(x['id'])!=str(player['id']) and
            x.get('availability') not in ('OUT','SCRATCHED','INJURED')]
    # Use the actual G9 coverage finding and G4 shooter release, only now.
    wins,rows=challenger_proof(player,rivals,weak,
        (coverage_data or {}).get('greenWeakZones'))
    # A same-route rival whose OWN direct evidence is strictly stronger owns
    # the route: that is a genuine G10.5 recipient-separation loss, not an
    # unresolved source gap. Unresolved rows (missing rival source, exact
    # ties) remain NOT_EXECUTED so research continues instead of a fake loss.
    route_owned_by=sorted(str(r['challengerId']) for r in rows
                          if r.get('status')=='RIVAL_DOMINATES'
                          and str(r['challengerId']) not in unresolved_before)
    unresolved_dominators=sorted(str(r['challengerId']) for r in rows
                          if r.get('status')=='RIVAL_DOMINATES'
                          and str(r['challengerId']) in unresolved_before)
    emit('G10.5',wins is True,
         {'comparisonRows':rows,'allAlternativesScanned':len(rows)==len(rivals),
          'noGuessTransfer':True,
          'challengersStoppedBeforeG10_5':{k:v for k,v in sorted(stopped.items())
                                           if k!=str(player['id'])} or None,
          'eliminatedChallengersExcluded':sorted(eliminated_before-{str(player['id'])}) or None,
          'unresolvedChallengersCannotEliminate':unresolved_dominators or None,
          'routeOwnedByStrongerRival':route_owned_by or None},
         eliminate=bool(route_owned_by),
         source_ids=sorted({url for row in rows for url in row.get('sourceUrls',[])
             if url} | ({player['release']['sourceUrl']} if receipt(player.get('release')) else set())))
    shots=player.get('pressure')
    recent_shots=evidence_data(shots,'recentAppearanceShots')
    # G11: observed own-shot pressure in separate actual appearances.
    # [0,0,3] is one isolated active game, not recurring pressure.
    emit('G11',bool(receipt(shots) and shot_review['valid']
                    and shot_review['repeatedOwnShotPressure']),
         {'recentOwnAttempts':recent_shots,
          'shotContinuation':shot_review,
          'noOneOffPressureCalledContinuation':True},
         # Missing appearance dates are an evidence gap, not proof that
         # the player failed to repeat his own shot pressure.
         eliminate=bool(receipt(shots) and shot_review['valid']
                        and shot_review['datedAppearanceAlignmentVerified']
                        and not shot_review['repeatedOwnShotPressure']),
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
    # G15: own GOAL FINISHER (not the assist provider), independently
    # corroborated by the official dated season goal log and the skater's
    # separate NHL EDGE own shot-origin record. G5 already proved which
    # observed own shooting lane attacks the G0 goalie weakness.
    #
    # A player may have actual shots but no historically credited goal in
    # that SPECIFIC weak lane while independently owning historical goals in
    # other lanes. Requiring a SAME-LANE goal here wrongly duplicates the
    # physical-lane G5 check and labels a real historical scorer NOT_EXECUTED
    # despite independent positive goal credits from both sources.
    # DO NOT claim any historical goal in the matched lane when there is zero.
    season_release_consistent=bool(
        verified_season_goals and release and
        type(release.get('ownedGoals')) is int and
        release['ownedGoals']<=season_data['officialPastSeasonGoals'])
    edge_routes=(release.get('allRoutes') or []) if release else []
    edge_full_own_goal_reconciliation=bool(
        verified_season_goals and receipt(player.get('release')) and
        isinstance(release,dict) and
        release.get('sourceType')=='NHL_EDGE_SHOT_ORIGIN_PEER_PERCENTILE' and
        isinstance(edge_routes,list) and len(edge_routes)>0 and
        all(isinstance(row,dict) and bool(row.get('zone')) and
            type(row.get('sog')) is int and row['sog']>=0 and
            type(row.get('ownedGoals')) is int and
            0<=row['ownedGoals']<=row['sog'] for row in edge_routes) and
        len({row.get('zone') for row in edge_routes})==len(edge_routes) and
        sum(row['ownedGoals'] for row in edge_routes)==
            season_data['officialPastSeasonGoals'] and
        release.get('attempts',0)>0 and
        (season_history or {}).get('sourceUrl') !=
            player['release']['sourceUrl'] and
        season_data['officialPastSeasonGoals']>0)
    # One direct finishing proof already in THIS chosen lane remains the
    # strongest form of historical route attribution. The independent
    # full-season cross-origin option is NOT a claim he scored from this
    # lane; it verifies a goal recipient who shoots from the targeted lane.
    exact_matched_lane_goal=bool(release and
        type(release.get('ownedGoals')) is int and
        release['ownedGoals']>0)
    finish_corrob=bool(
        own and own.get('recipient') is True and
        receipt(ownership) and rec and
        (sample_goals or season_release_consistent) and
        receipt(player.get('release')) and release and
        type(release.get('ownedGoals')) is int and
        (exact_matched_lane_goal or edge_full_own_goal_reconciliation))
    emit('G15',finish_corrob,
         {'independentHistoricalGoalFinishingEvidence':finish_corrob,
          'goalSourceReconciledToDatedAppearances':bool(rec),
          'separateOfficialShotOriginSource':bool(receipt(player.get('release'))),
          'officialOwnedGoalsInMatchedOrigin':release.get('ownedGoals') if release else None,
          'matchedOriginOwnOnNetShots':release.get('attempts') if release else None,
          'matchedOriginHasHistoricalGoal':exact_matched_lane_goal,
          'officialDatedSeasonGoals':season_data.get('officialPastSeasonGoals') if verified_season_goals else None,
          'totalOwnedGoalsFromEveryNhlEdgeOrigin':sum(
              row.get('ownedGoals',0) for row in edge_routes
              if isinstance(row,dict) and type(row.get('ownedGoals')) is int)
              if edge_routes else None,
          'fullSeasonGoalCreditsReconciledAgainstEdgeOrigins':edge_full_own_goal_reconciliation,
          'directFinisherEvidenceMethod':(
              'POSITIVE_OWN_GOALS_FROM_MATCHED_ROUTE' if exact_matched_lane_goal else
              'OFFICIAL_FULL_SEASON_GOALS_MATCH_ALL_EDGE_OWN_ORIGINS_AND_SOURCED_MATCHED_LANE_SHOTS'
              if edge_full_own_goal_reconciliation else None),
          'sameLaneGoalsNotInferredFromScoringElsewhere':True,
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
          'includesDepthAndDefense':True,
          'routeOwnedByStrongerRival':route_owned_by or None,
          'crossGameFinalistCompetitionRunsAfterEveryGame':True,
          'challengersStoppedBeforeG10_5':stopped or None,
          'eliminatedChallengersExcluded':sorted(eliminated_before-{str(player['id'])}) or None,
          'unresolvedChallengersCannotEliminate':unresolved_dominators or None},
         eliminate=bool(route_owned_by),
         # The candidate side of every comparison is its own official release
         # record, so it is cited even when no live challenger remains.
         source_ids=sorted(set([url for row in rows for url in row.get('sourceUrls',[])
             if isinstance(url,str) and url.startswith('https://')]+
             ([player['release']['sourceUrl']] if receipt(player.get('release')) else []))))
    contradiction=player.get('contradictions')
    cdata=evidence_data(contradiction)
    # Having a review OBJECT is not proof that its conflicts were resolved.
    # Source-derived cross-checks must explicitly report no unresolved
    # goalie/role/rival contradiction to pass; never force G17 on placeholder.
    # G17's contradiction decision is authoritative regardless of which
    # independent source supplied the structured review. Previously ANY
    # non-DERIVED source with unresolved=True was silently marked PASS.
    # Require a positive resolved outcome, not merely a source label.
    cross_source_resolved=bool(cdata and cdata.get('unresolved') is False)
    # The pregame review compared every teammate, including teammates the
    # gates already ELIMINATED. Like G10.5/G16, such a teammate is not a
    # meaningful rival and cannot keep this candidate's G17 unresolved. Every
    # other stored review condition (goalie branch, weak-area match, stronger
    # area contradiction, lineup role, unresolved live rivals) still applies.
    g17_live=g17_resolved_without_eliminated_rivals(cdata,eliminated_before)
    if not cross_source_resolved and g17_live['resolved']:
        cross_source_resolved=True
    emit('G17',bool(cdata and cdata.get('goalieStrengthReview') is not None and
                     cdata.get('lineupDisagreementReview') is not None and
                     cdata.get('strongestRivalReview') is not None and
                     cross_source_resolved),
         {'goalieBranch':goalie_profile['data'].get('goalieId'),
          'counterevidence':cdata,'retainsConflictingSources':True,
          'sourceDerivedReviewResolved':cross_source_resolved,
          'eliminatedRivalsIgnoredInRivalReview':g17_live['ignoredEliminatedRivals'] or None},
         source_ids=[contradiction['sourceUrl']] if receipt(contradiction) else [])
    # Both independent tracks must pass. Neither may overwrite the other's
    # original verdict or masquerade as a completed source check.
    master_passed=all(d[gate]['disposition']=='PASS'
                      for gate in MASTER[:-1])
    # Step13 is the original qualitative, nonblocking numerology review.
    # Its evidence and verdict remain visible, but a missing optional
    # observation must not eliminate an otherwise source-qualified scorer.
    overlay_passed=all(
        row['disposition']=='PASS' or
        (row['gate']=='Step13' and
         row.get('details',{}).get('evidence',{}).get('nonblocking') is True)
        for row in overlay)
    previous_gates_passed=master_passed and overlay_passed
    route,path_proof=adjudicate_scoring_path(player,teammates,release,
        goalie_profile,coverage,d,rows,who_ok)
    passed=previous_gates_passed and route is not None
    # In the scheduled full-slate run G18 is deferred until G16 finishes
    # cross-game competition. A game finalist is NOT yet a Core recipient.
    if not defer_g18:
        emit('G18',passed,{
            'candidateEligibleForCrossGameFinal':passed,
            'pathClassificationEvidence':path_proof,
            'classificationOccursAfterAllSourceGates':True,
            'originalFunctionsReviewedBeforeG18':overlay_passed,
            'notPresetOneOfEach':True},
            source_ids=path_proof['sourceUrls'])
    master_trace=[row['gate'] for row in proof]
    overlay_trace=[row['gate'] for row in overlay]
    expected_master=MASTER[:-1] if defer_g18 else MASTER
    if master_trace!=expected_master:
        raise ValueError(f'Master scorer-gate execution order mismatch: {master_trace}')
    if set(overlay_trace)!=set(OVERLAY) or len(overlay_trace)!=len(OVERLAY):
        raise ValueError(f'Gate-time source observation coverage mismatch: {overlay_trace}')
    expected_execution=EXECUTION_ORDER[:-1] if defer_g18 else EXECUTION_ORDER
    if [row['gate'] for row in execution_trace]!=expected_execution:
        raise ValueError('Single original gate trace does not match G0–G18')
    final_g18_passed=(passed if defer_g18 else
                      passed and d['G18']['disposition']=='PASS')
    return {'player':player,'dispositions':d,'complete':final_g18_passed,
            'preCoreQualified':passed,'g18Deferred':defer_g18,
            'deficientGates':deficient,'route':route,'pathEvidence':path_proof,
            'pressure':evidence_data(shots),
            'release':release,'challengers':rows},execution_trace


def verify_complete_matrix(games, records, scan, now=None, selected_directions=None):
    """Verify each original gate and its internal source functions before G18."""
    errors=[]
    now=now or datetime.now(timezone.utc)
    expected_set=set(EXECUTION_ORDER)
    if set(OVERLAY)!=set(STEP_ORDER):
        errors.append('Phase-1 overlay source order differs from the authoritative mapping')
    for game in games:
        already_started=(game.get('gameState') in ('LIVE','CRIT','OFF','FINAL') or
          (game.get('startUTC') and datetime.fromisoformat(game['startUTC'].replace('Z','+00:00'))<=now))
        if already_started:continue
        direction=(selected_directions or {}).get(str(game['id']))
        if not direction:
            # G0 is itself an executed gate, even when its evidence does not
            # establish a direction. Verify both recorded attack-side reviews
            # rather than silently treating the matchup as absent.
            direction_rows=[r for r in records
                if r['gameId']==str(game['id']) and r['gate']=='G0'
                and r['playerId'].startswith('GOALIE_DIRECTION:')]
            expected_attackers={
                'GOALIE_DIRECTION:'+str(game['away']),
                'GOALIE_DIRECTION:'+str(game['home'])}
            if {r['playerId'] for r in direction_rows}!=expected_attackers:
                errors.append(f"{game['id']} G0 both attack directions not executed")
            continue  # Skater gates require an evidenced G0 attack direction
        active_roster=complete_roster(game,direction['attacker'])
        for person in active_roster:
            pid=str(person['id'])
            candidate_records=[r for r in records
                if r['gameId']==str(game['id']) and r['playerId']==pid]
            actual=[r['gate'] for r in candidate_records]
            if set(actual)!=expected_set:
                missing=[gate for gate in EXECUTION_ORDER if gate not in set(actual)]
                errors.append(f"{game['id']} player {pid} missing original gate records {missing}")
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
            # Source functions are evidence within each original gate; they
            # cannot be skipped, copied from its verdict, or stored as gates.
            for entry in candidate_records:
                gate=entry['gate']
                expected=STEPS_BY_GATE[gate]
                content=(entry.get('details') or {}).get('evidence') or {}
                functions=content.get('originalFunctionEvidence') or []
                actual_steps=[x.get('step') for x in functions]
                if actual_steps!=expected:
                    errors.append(
                        f"{game['id']} player {pid} gate {gate} missing original functions "
                        f"{expected}: got {actual_steps}")
                for fn in functions:
                    ev=fn.get('evidence') or {}
                    if not (ev.get('independentOverlayEvaluation') is True
                            and ev.get('checkedBeforeG18') is True
                            and ev.get('masterGateVerdictCopied') is False):
                        errors.append(
                            f"{game['id']} player {pid} gate {gate} "
                            f"function {fn.get('step')} lacks independent evidence")
        count=sum(1 for r in records if r['gameId']==str(game['id']) and r['gate']=='G0'
                  and r['playerId'].startswith('GOALIE_DIRECTION:'))
        if count!=2:errors.append(f"{game['id']} G0 source directions saved {count} not 2")
    return errors


# G17 evidence-status levels: a source-CONFIRMED goalie/role carries less
# branch uncertainty than an EXPECTED/PROJECTED one. Ordinal only, never a
# weight; EXPECTED and PROJECTED are the same (unconfirmed) level.
_STATUS_LEVEL={'CONFIRMED':2,'EXPECTED':1,'PROJECTED':1}


def finalist_route_evidence(item):
    """The exact G10.5/G11/G17 evidence a per-game survivor carries into G16."""
    cand=item['candidate']; release=cand.get('release') or {}
    goalie=(item.get('targetGoalie') or {}).get('data') or {}
    dep=evidence_data(cand['player'].get('deployment')) or {}
    return {
        'gameId':str(item['game']['id']),
        'playerId':str(cand['player']['id']),
        'player':cand['player'].get('name'),
        'routeZone':release.get('zone'),
        # G10.5 direct-route evidence: own credited goals from the matched
        # lane, then own on-net shots from that same lane.
        'ownedGoalsInMatchedLane':release.get('ownedGoals'),
        'ownShotsOnGoalInMatchedLane':release.get('attempts'),
        # G17 branch uncertainty.
        'goalieStatus':goalie.get('status'),
        'deploymentStatus':dep.get('status'),
    }


def _route_vector(ev):
    goals=ev['ownedGoalsInMatchedLane']; shots=ev['ownShotsOnGoalInMatchedLane']
    if type(goals) is not int or type(shots) is not int:
        return None
    return (goals,shots,_STATUS_LEVEL.get(ev['goalieStatus'],0),
            _STATUS_LEVEL.get(ev['deploymentStatus'],0))


def _dominates(a,b):
    """a strictly dominates b: at least as strong on EVERY dimension and
    stronger on at least one. No sums, weights, rates or tie-breaks."""
    return all(x>=y for x,y in zip(a,b)) and any(x>y for x,y in zip(a,b))


def g16_cross_game_finalists(finalists, required):
    """G16 FINAL CHALLENGER COMPETITION across every per-game survivor.

    Each finalist already won G0-G17 inside its own game. G16 now compares
    all meaningful surviving candidates, using only the original direct
    evidence: G10.5 own goals and own on-net shots from the matched lane,
    plus G17 goalie/deployment confirmation status.

    A finalist is excluded only when at least ``required`` finalists from
    OTHER games each strictly dominate it, i.e. a full Core can be built
    entirely from routes that are at least as strong on every dimension and
    stronger on one. Nothing is summed, weighted or tie-broken. If more than
    ``required`` finalists remain unseparated, there is no Core and the
    receipt says exactly which finalists remain tied.
    """
    rows=[]
    vectors=[]
    for item in finalists:
        ev=finalist_route_evidence(item)
        vectors.append(_route_vector(ev))
        rows.append(ev)
    retained=[];excluded=[]
    for i,(ev,vec) in enumerate(zip(rows,vectors)):
        if vec is None:
            ev['g16Decision']='RETAINED_ROUTE_EVIDENCE_NOT_COMPARABLE'
            ev['dominatedBy']=[]
            retained.append(i); continue
        by=[rows[j]['playerId'] for j,other in enumerate(vectors)
            if j!=i and other is not None and
            rows[j]['gameId']!=ev['gameId'] and _dominates(other,vec)]
        ev['dominatedBy']=by
        if len(by)>=required:
            ev['g16Decision']='EXCLUDED_STRICTLY_DOMINATED_BY_A_FULL_CORE'
            excluded.append(i)
        else:
            ev['g16Decision']='RETAINED'
            retained.append(i)
    receipt_out={
        'gate':'G16','phase':'CROSS_GAME_FINALIST_COMPETITION',
        'requiredCoreSize':required,
        'finalistCount':len(finalists),
        'finalists':rows,
        'retainedPlayerIds':[rows[i]['playerId'] for i in retained],
        'excludedPlayerIds':[rows[i]['playerId'] for i in excluded],
        'comparisonDimensions':['G10.5 ownedGoalsInMatchedLane',
            'G10.5/G11 ownShotsOnGoalInMatchedLane',
            'G17 goalieStatus (CONFIRMED > EXPECTED/PROJECTED)',
            'G17 deploymentStatus (CONFIRMED > PROJECTED)'],
        'rule':('Exclude a finalist only if >= requiredCoreSize finalists from '
                'other games strictly dominate it on every dimension'),
        'noWeightsSumsRatesOrTieBreaks':True,
        'noStarPP1OrOddsPreference':True,
        'separated':len(retained)==required,
    }
    return [finalists[i] for i in retained],receipt_out


def cross_game_winners(winners, slate_size):
    """G18 ONLY ASSEMBLES THE CORE produced by prior independent gates.

    G0-G17, G10.5 and the complete independent overlay decide who survives.
    G18 never runs another rank, weighted/lexicographic/dominance score,
    goalie-percentile comparison, or source-evidence threshold. It merely
    places three distinct-game survivors (two on a two-game slate) onto
    the one canonical card.

    If earlier gates have not uniquely settled that Core, the solution is
    to resolve their actual source evidence, not for G18 to invent a winner.
    """
    required=2 if slate_size==2 else 3
    game_ids=[str(item['game']['id']) for item in winners]
    if len(game_ids)!=len(set(game_ids)):
        return [],['PRE_CORE_REVIEW: multiple survivors from one game; G10.5/G17 must separate recipients before final Core assembly']
    if len(winners)!=required:
        return [],[f'PRE_CORE_REVIEW: {len(winners)} independently qualified game recipients, '
                   f'but Core {required} requires exactly {required}; G18 cannot '
                   'rank, preselect, or eliminate any of them']
    return list(winners),[]


def _authorized_retraction_reselection(con, existing, legs, selected, date, stage):
    """Repair a previously REVOKED November 17 card from a fresh full-gate run.

    The one-slate user-authorized retraction archived the bad G18 selection,
    but a later run reissued the SAME bad fingerprint. Normal goalie-only
    replacement cannot correct a wrong GAME recipient. This exception does
    not elect any scorer: it uses only the already-executed G16/G18 survivors
    and independently saved source receipts. An unknown prior gate is recorded
    as NOT_EXECUTED, never misrepresented as source elimination.
    """
    if date != '2026-11-17' or stage not in ('PROJECTED', 'CONFIRMED'):
        return None
    try:
        archived = con.execute(
            "SELECT original_fingerprint,original_card FROM card_retractions "
            "WHERE slate_date=?", (date,)).fetchone()
    except Exception:
        return None
    if not archived or existing.get('grade') is not None:
        return None
    old_original = json.loads(archived['original_card'])
    if (archived['original_fingerprint'] != existing['fingerprint']
            or old_original.get('fingerprint') != existing['fingerprint']
            or str(existing['first_issued_at']) <= str(old_original['first_issued_at'])):
        return None

    old_by_id = {(str(x['gameId']), str(x['playerId'])): x
                 for x in existing['current_legs']}
    new_by_id = {(str(x['gameId']), str(x['playerId'])): x for x in legs}
    removed = [old_by_id[k] for k in old_by_id.keys() - new_by_id.keys()]
    added = [new_by_id[k] for k in new_by_id.keys() - old_by_id.keys()]
    if len(removed) != 1 or len(added) != 1 or len(legs) != len(existing['current_legs']):
        return None
    old, new = removed[0], added[0]

    # Current G0-G18 is the selection authority, not the historical card.
    # The engine has just saved these rows for the SAME phase/source snapshot.
    chosen_ids = {(str(x['game']['id']), str(x['candidate']['player']['id']))
                  for x in selected}
    if chosen_ids != set(new_by_id) or len(selected) != len(legs):
        return None
    if any(not item['candidate'].get('complete') or any(
            (item['candidate'].get('dispositions', {}).get(g) or {}).get('disposition') != 'PASS'
            for g in MASTER) for item in selected):
        return None
    candidate_item = next((x for x in selected
        if str(x['game']['id']) == str(new['gameId'])
        and str(x['candidate']['player']['id']) == str(new['playerId'])), None)
    if candidate_item is None:
        return None
    candidate = candidate_item['candidate']
    comparison = candidate.get('challengers') or []
    if (not comparison or
            any(row.get('status') not in (
                'DEFEATED', 'DIFFERENT_TARGET_LANE',
                'SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE')
                for row in comparison)):
        return None

    # Prove why the previously retracted recipient no longer has a CURRENT
    # certified route. Source-unknown is never upgraded to ELIMINATED.
    previous = con.execute(
        "SELECT gate,disposition,details FROM gates WHERE slate_date=? "
        "AND stage=? AND game_id=? AND player_id=? AND gate!='G18'",
        (date, stage, str(old['gameId']), str(old['playerId']))).fetchall()
    prior_nonpass = next((row for gate in ('G10.5','G15','G16','G17',
        'G0','G1','G2','G3','G4','G5','G6','G7','G8','G9','G10','G11','G12','G13','G14')
        for row in previous if row['gate'] == gate and
        row['disposition'] in ('ELIMINATED', 'NOT_EXECUTED')), None)
    if not prior_nonpass:
        return None

    # Match the source IDs to persisted immutable evidence; URL-only prose
    # cannot satisfy the ledger's audited replacement contract.
    old_receipt = con.execute(
        "SELECT evidence_id FROM evidence WHERE slate_date=? AND game_id=? "
        "AND player_id=? ORDER BY evidence_id LIMIT 1",
        (date, str(old['gameId']), str(old['playerId']))).fetchone()
    release = candidate['player'].get('release') or {}
    g17 = candidate['player'].get('contradictions') or {}
    new_id, g17id = release.get('evidenceId'), g17.get('evidenceId')
    for ref in (new_id, g17id):
        if not ref or not con.execute(
            "SELECT 1 FROM evidence WHERE slate_date=? AND evidence_id=? "
            "AND game_id=? AND player_id=?",
            (date, ref, str(new['gameId']), str(new['playerId']))).fetchone():
            return None
    if not old_receipt:
        return None
    return {
        'baselineFingerprint': existing['fingerprint'],
        'triggerEvidenceId': new_id,
        'oldValue': {'player': old['player'], 'gameId': old['gameId']},
        'newValue': {'player': new['player'], 'gameId': new['gameId']},
        'affectedGates': ['G10.5','G15','G16','G17','G18'],
        'dependentGates': ['G10.5','G15','G16','G17','G18'],
        'priorSurvivorFailure': {
            'playerId': old['playerId'],
            'failedGate': prior_nonpass['gate'],
            'disposition': prior_nonpass['disposition'],
            'sourceIds': [old_receipt['evidence_id']],
            'savedGateEvidence': json.loads(prior_nonpass['details']),
            'notAnEliminationWhenMissing': prior_nonpass['disposition'] == 'NOT_EXECUTED',
            'reason': 'Previously user-retracted card; current gate evidence is not a PASS',
        },
        'g105EveryChallenger': {'candidate': new['playerId'],
                                'comparisonRows': comparison},
        'g17Contradictions': {
            'sourceIds': [g17id],
            'review': candidate['dispositions']['G17']['details']},
        'newFingerprint': fingerprint(legs),
        'exceptionScope': 'NOV17_PREVIOUSLY_RETRACTED_FINGERPRINT_ONLY',
        'retractedOriginalFirstIssuedAt': old_original['first_issued_at'],
        'notAManualSelection': True,
    }


def build_verified_replacement(con, existing, legs, selected, date, stage):
    """Automatic pre-puck replacement only after source-backed gate reruns."""
    corrected = _authorized_retraction_reselection(
        con, existing, legs, selected, date, stage)
    if corrected is not None:
        return corrected
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
        # NHL EDGE and some sampled PBP peer ranks are rounded into discrete
        # percentile bands. Equal *published* percentiles do NOT mean equal
        # measured direct scoring vulnerability if the official goal/on-net
        # shot fractions are independently different. Compare those ACTUAL
        # source observations, not goalie fame, shot volume, home/away status,
        # team goal forecasts, or an invented numerical weight.
        #
        # Both goalies must have a UNIQUE weakest peer-ranked origin. If
        # either goalie has multiple tied origins, the raw-rate selection
        # would arbitrarily pick an area and MUST remain unresolved.
        for profile,weakest_row in ((pa,weakest_a),(pb,weakest_b)):
            all_weak=profile.get('weakZones') or {}
            if sum(type(z.get(key)) in (int,float) and
                   z.get(key)==weakest_row[0] for z in all_weak.values())!=1:
                return None
        _,zone_a,na,ga,_=weakest_a
        _,zone_b,nb,gb,_=weakest_b
        if ga*nb==gb*na:
            return None  # a real empirical tie, not an unresolved round-off
        chosen,other=(a,b) if ga*nb>gb*na else (b,a)
        win,lose=(weakest_a,weakest_b) if ga*nb>gb*na else (weakest_b,weakest_a)
        return {**chosen,
            'g0SelectionMethod':'TIED_PUBLISHED_PEER_PERCENTILE_DIRECT_OBSERVED_GOAL_RATE',
            'g0SelectedOnlyAfterBothStarterProfiles':True,
            'g0DecisionProof':{
                'reason':'Official peer percentiles tied, but independently observed direct goals per on-net shot differed at each goalie’s uniquely weakest source-supported origin',
                'winnerWeakOrigin':win[1],'oppositeWeakOrigin':lose[1],
                'winnerGoalieOnNetShots':win[2],'winnerGoalsAllowedFromOrigin':win[3],
                'oppositeGoalieOnNetShots':lose[2],'oppositeGoalsAllowedFromOrigin':lose[3],
                'publishedEqualPeerSavePercentile':score_a,
                'directRateComparedByExactIntegerCrossProduct':True,
                'uniqueWeakestOriginForEachGoalie':True,
                'sourceClassSameForBothGoalies':src_a,
                'noWeightsOrExternalOdds':True,
                'notGloveBlockerFiveHole':True,
                'oppositeDirectionSourceReviewed':True,
                'goalieSourceUrls':[pa.get('goalieProfileSourceUrl') or pa.get('sourceUrl'),
                                    pb.get('goalieProfileSourceUrl') or pb.get('sourceUrl')],
                'noScorerOrTeamPopularityComparison':True,
            }}
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
    if not wa and not wb:return None
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
    if not wa or not wb:
        one_sided=_g0_pbp_one_sided_weakness(a,b,pa,pb,da,db,wa,wb,qualified)
        if one_sided is None:return None
        original,proof=one_sided
        return {**original,
            'g0SelectionMethod':'SAME_HISTORICAL_OFFICIAL_PBP_ONE_SIDED_WEAKNESS',
            'g0SelectedOnlyAfterBothStarterProfiles':True,
            'g0DecisionProof':{
                **proof,
                'reason':'Same pre-slate official PBP peer pool: only one goalie has a peer-qualified weak origin, and the other goalie is better on BOTH goal rate and peer rank from every one of those origins',
                'samePeerPopulationId':population,
                'goaliePbpSourceUrls':[pa['sourceUrl'],pb['sourceUrl']],
                'sourceCoherentIndependentHistoricalSample':True,
                'opposingGoaliesIndividuallyIdentified':True,
                'noWeightsOrExternalOdds':True,
                'notGloveBlockerFiveHole':True,
                'notGuaranteedTonightGoal':True,
            }}
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


def _g0_pbp_one_sided_weakness(a,b,pa,pb,da,db,wa,wb,qualified):
    """Same-cohort PBP: one goalie has peer-qualified weak origins, the other none.

    Mirrors the existing EDGE superset rule (a source-reviewed goalie with no
    weak origin is negative evidence, not missing evidence) but demands more:
    for EVERY weak origin of the exposed goalie, the other goalie must have a
    peer-compared row from that SAME origin in the SAME population and be
    better on BOTH direct goals-per-on-net-shot and peer save rank. Any
    missing comparator, tie, or disagreement leaves G0 unresolved.
    """
    if wa and wb:return None
    weak_side,weak,other_data=('a',wa,db) if wa else ('b',wb,da)
    if not weak:return None
    other_areas=other_data.get('observedAreas') or {}
    if not (type(other_data.get('fullySourceComparedAreas')) is int
            and other_data['fullySourceComparedAreas']>0):
        return None
    rows=[]
    for zone in sorted(weak):
        x=weak[zone];y=other_areas.get(zone)
        if not isinstance(y,dict) or not qualified_row(y):
            return None
        nx,ny=x['shotsAgainst'],y['shotsAgainst']
        gx,gy=x['goalsAgainst'],y['goalsAgainst']
        rx,ry=x['samplePeerSavePctgPercentile'],y['samplePeerSavePctgPercentile']
        if not (rx<ry and gx*ny>gy*nx):
            return None
        rows.append({'origin':zone,
            'exposedGoalieShots':nx,'exposedGoalieGoals':gx,'exposedGoaliePeerRank':rx,
            'otherGoalieShots':ny,'otherGoalieGoals':gy,'otherGoaliePeerRank':ry})
    original=a if weak_side=='a' else b
    other=b if weak_side=='a' else a
    return original,{
        'exposedGoalieId':str((da if weak_side=='a' else db).get('goalieId')),
        'otherGoalieId':str(other_data.get('goalieId')),
        'otherGoalieWeakOrigins':[],
        'otherGoalieFullySourceComparedAreas':other_data['fullySourceComparedAreas'],
        'sameOriginComparisons':rows,
        'everyExposedOriginDirectlyCompared':True,
        'oppositeDirectionSourceReviewed':True,
        'oppositeAttacker':other.get('attacker'),
    }


def qualified_row(v):
    """Same per-origin floor used by compare_g0_shared_official_pbp."""
    return (isinstance(v,dict) and type(v.get('shotsAgainst')) is int
            and v['shotsAgainst']>=20
            and type(v.get('goalsAgainst')) is int
            and 0<=v['goalsAgainst']<=v['shotsAgainst']
            and type(v.get('samplePeerSavePctgPercentile')) in (int,float)
            and 0<=v['samplePeerSavePctgPercentile']<=1
            and v.get('peerComparedSameOrigin') is True
            and type(v.get('peerGoaliesSampled')) is int
            and v['peerGoaliesSampled']>=4)


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
    # Postgame learning is audit-only: original gate verdicts alone select scorers.
    records=[];qualified=[];all_survivor_receipts=[];pool_size=0
    deferred_g18=[]  # All candidate G18 receipts wait for the G16 decision
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
        if consensus is not None and len(consensus['targetGoalies'])==1:
            selected_directions[str(match['id'])]=consensus
            continue
        if consensus is not None:
            # An attack side can be consistent across all projected goalies,
            # yet a SPECIFIC opposing goalie still isn't independently
            # identified. The scorer matrix is keyed by official player ID,
            # so proceeding through two goalie branches would overwrite the
            # other branch's source proof and falsely certify one result.
            # Continue ALL source checks in namespaced G0 research instead.
            errors.append(f"{match['id']} G0 source consensus exists but multiple potential opposing goalies remain; cannot bind unique scorer-to-goalie route")
            continue
        errors.append(f"{match['id']} G0 neither a shared official goalie-peer comparison nor unanimous projected-starter evidence distinguished the attacking direction")
    # Always refresh G17 AFTER G0 identifies the attack side and exact goalie.
    # A pre-G0 review may be source-backed yet tied to another goalie branch
    # or an unscoped rival cohort. The old conditional only retried when the
    # receipt was absent, silently reusing an outdated contradictory review.
    # The reviewer records a NEW immutable source receipt; it never copies a
    # PASS from G0, and unresolved contradictions still fail G17.
    eligible_g17_directions={
        str(g['id']):selected_directions[str(g['id'])]
        for g in games if str(g['id']) in selected_directions and
        g.get('gameState') not in ('LIVE','CRIT','OFF','FINAL') and
        (not g.get('startUTC') or
         datetime.fromisoformat(g['startUTC'].replace('Z','+00:00'))>now)
    }
    if eligible_g17_directions:
        from .contradiction_review import review_all_candidates
        from .enrichment import attach
        review_all_candidates(con,snapshot,date,stage,
                              selected_directions=eligible_g17_directions)
        # Re-attach the latest independent G17 source to the G0-selected
        # official player IDs before any scorer gate is evaluated.
        attach(con,snapshot,date,stage)
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
                scoped_players=[release_matched_to_g0_target(
                    player,branch,match.get('coverage',{}).get(attacker)) for player in players]
                stopped=stopped_before_g10_5([
                    evaluate_skater(match,attacker,x,players,branch,stage)[0]
                    for x in scoped_players])
                for player,scoped in zip(players,scoped_players):
                    # No _g0SelectedDirection: these are NOT proposed Core
                    # paths. Every gate is physically checked with the real
                    # source branch, but G0 and G18 must remain nonpassing.
                    candidate,trace=evaluate_skater(
                        match,attacker,scoped,players,branch,stage,
                        stopped_before_g10_5=stopped)
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
    # game_pool: every game's own Blender outcome (the Core player pool).
    # Display/receipt only; it never selects, ranks or reopens anyone.
    game_pool={}
    def pool_entry(match,status,**extra):
        game_pool[str(match['id'])]={'gameId':str(match['id']),
            'matchup':match['away']+'@'+match['home'],
            'gameStartUTC':match.get('startUTC'),'status':status,**extra}
    for match in games:
        is_started=match.get('gameState') in ('LIVE','CRIT','OFF','FINAL') or (
            match.get('startUTC') and datetime.fromisoformat(match['startUTC'].replace('Z','+00:00')) <= now)
        if is_started:
            # Not eligible for new selection; frozen cards remain in storage.
            pool_entry(match,'STARTED_NOT_ELIGIBLE_FOR_NEW_SELECTION')
            continue
        direction=selected_directions.get(str(match['id']))
        if direction is None:
            pool_entry(match,'NO_SURVIVOR',stoppedAt='G0',
                       reason='G0 did not decide which goalie is attacked')
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
        first_stops=defaultdict(int); furthest={}
        for original_branch in branches:
            branch=g0_source_coherent_scorer_goalie(match,direction,original_branch)
            scoped_game={**match,'_g0SelectedDirection':direction}
            scoped_players=[release_matched_to_g0_target(player,branch,match.get('coverage',{}).get(team))
                            for player in players]
            # Pass 1 only establishes who passed G0-G10 (teammate-independent).
            stopped=stopped_before_g10_5([
                evaluate_skater(scoped_game,team,x,players,branch,stage,defer_g18=True)[0]
                for x in scoped_players])
            for scoped in scoped_players:
                # Bind the G0 direction receipt to every skater checked after
                # goalie-first selection; never infer direction from a PASS.
                result,traces=evaluate_skater(scoped_game,team,scoped,players,branch,stage,
                                              stopped_before_g10_5=stopped,defer_g18=True)
                records+=traces
                deferred_g18.append((match,result))
                stop=next((g for g in MASTER[:-1] if
                           (result['dispositions'].get(g) or {}).get('disposition')!='PASS'),None)
                if stop:
                    stop_label=f"{stop}:{result['dispositions'][stop]['disposition']}"
                    first_stops[stop_label]+=1
                    furthest.setdefault(MASTER.index(stop),[]).append({
                        'playerId':str(result['player']['id']),
                        'player':result['player'].get('name'),'stoppedAt':stop_label})
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
        far=furthest.get(max(furthest)) if furthest else []
        base=dict(attackTeam=team,opponentTeam=opponent,
                  targetGoalieIds=[b['data'].get('goalieId') for b in branches],
                  candidatesEvaluated=len(players),
                  firstNonPassGateCounts=dict(sorted(first_stops.items())),
                  furthestCandidatesDiagnosticOnly=far[:5] if len(all_per_game)==0 else [])
        if len(all_per_game)==1:
            own=all_per_game[0]['candidate']['player']
            pool_entry(match,'SURVIVOR',**base,survivor=next(
                (r for r in all_survivor_receipts if r['gameId']==str(match['id'])
                 and r['playerId']==str(own['id'])),{'playerId':str(own['id']),'player':own.get('name')}))
        elif len(all_per_game)>1:
            pool_entry(match,'UNSEPARATED_SAME_GAME_SURVIVORS',**base,
                       survivors=[{'playerId':str(x['candidate']['player']['id']),
                                   'player':x['candidate']['player'].get('name')} for x in all_per_game])
        else:
            pool_entry(match,'NO_SURVIVOR',**base,
                       # The furthest first failure of any REJECTED skater is
                       # not a uniquely remaining game-wide source blocker.
                       furthestFirstNonPassGate=MASTER[max(furthest)] if furthest else None,
                       reason='no candidate passed every pre-Core gate G0-G17')
        if len(all_per_game)==1:
            qualified.append(all_per_game[0])
        elif len(all_per_game)>1:
            # G18 is the final Core CARD, not a new game-level scorer ranker.
            # Keep all fully qualified source receipts; require the original
            # G10.5/G17 comparison to actually separate same-game rivals.
            errors.append(
                f"{match['id']} PRE_CORE_REVIEW: {len(all_per_game)} qualified same-game "
                "recipients remain after G10.5/G17; no arbitrary final pick")
    pool_size+=unresolved_unique_pool
    required_core=2 if len(games)==2 else 3
    g16_receipt=None
    finalists=qualified
    if len(qualified)>required_core and len(
            {str(x['game']['id']) for x in qualified})==len(qualified):
        finalists,g16_receipt=g16_cross_game_finalists(qualified,required_core)
    chosen,selection_errors=cross_game_winners(finalists,len(games))
    if g16_receipt and not g16_receipt['separated']:
        selection_errors.insert(0,
            f"G16 cross-game finalist competition left {len(finalists)} "
            f"unseparated finalists for a Core {required_core}: "
            f"{', '.join(g16_receipt['retainedPlayerIds'])}; no ranking or tie-break applied")
    # Finish the same G16 adjudication across ALL game survivors before
    # writing the only authoritative G18 final-card decision.
    final_keys={(str(x['game']['id']),str(x['candidate']['player']['id']))
                for x in chosen} if not selection_errors else set()
    decisions={(str(x['gameId']),str(x['playerId'])):x
               for x in ((g16_receipt or {}).get('finalists') or [])}
    for match,candidate in deferred_g18:
        key=(str(match['id']),str(candidate['player']['id']))
        finalist=decisions.get(key)
        if finalist:
            # The per-game G16 check was provisional: its global verdict now
            # becomes the one source-backed G16 gate decision.
            for row in records:
                if (row['gameId'],row['playerId'],row['gate'])==(key[0],key[1],'G16'):
                    evidence=row['details']['evidence']
                    evidence['crossGameFinalistCompetition']={
                        'decision':finalist['g16Decision'],
                        'dominatedBy':finalist['dominatedBy'],
                        'comparedAgainstAllGames':True,
                        'requiredCoreSize':required_core}
                    if finalist['g16Decision'].startswith('EXCLUDED_'):
                        row['disposition']='ELIMINATED'
                        candidate['dispositions']['G16']['disposition']='ELIMINATED'
                    break
        selected=key in final_keys and candidate['complete']
        proof={
            'candidateEligibleForCrossGameFinal':bool(candidate['preCoreQualified']),
            'pathClassificationEvidence':candidate['pathEvidence'],
            'classificationOccursAfterAllSourceGates':True,
            'originalFunctionsReviewedBeforeG18':True,
            'notPresetOneOfEach':True,
            'G18FinalAssemblyAfterFullG16':True,
            'G18CoreSlotGrantedOnlyAfterG16':bool(selected),
            'G16FinalistDecision':(finalist or {}).get('g16Decision'),
            'G16Exclusion':(finalist or {}).get('dominatedBy',[]) if not selected else [],
        }
        urls=candidate['pathEvidence'].get('sourceUrls',[])
        gaps=audit_gate('G18',proof,urls,stage) if selected else []
        if gaps:
            selection_errors.append(
                f"{key[0]} player {key[1]} G18 final source certification: {gaps}")
            proof['semanticProofGaps']=gaps
        disposition='PASS' if selected and not gaps else 'NOT_EXECUTED'
        candidate['dispositions']['G18']={'disposition':disposition,'details':proof}
        candidate['complete']=disposition=='PASS'
        records.append(gate_record(match,key[1],'G18',disposition,proof,urls))
    # Exactly one authoritative row for every original gate per skater.
    # Only the true final Core recipients are allowed a G18 PASS.
    save_gates(con,date,stage,records)
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
                   ' G0 both attack directions REQUIRE independent goalie profiles' in message or
                   ' G0 neither a shared official goalie-peer comparison nor unanimous projected-starter evidence distinguished the attacking direction' in message)
                  and message.split(' ',1)[0] not in selected_game_ids):
                nonselected_game_notes.append(message)
            else:
                remaining.append(message)
        errors=remaining
    gaps=defaultdict(int)
    g18_intentionally_not_selected=0
    for rec in records:
        if rec['disposition']!='NOT_EXECUTED':
            continue
        # A non-Core player deliberately does not pass final assembly G18.
        # This is not a missing G18 source, and must not inflate source gaps.
        evidence=(rec.get('details') or {}).get('evidence') or {}
        if (rec['gate']=='G18' and
            evidence.get('G18FinalAssemblyAfterFullG16') is True and
            evidence.get('G18CoreSlotGrantedOnlyAfterG16') is False):
            g18_intentionally_not_selected+=1
        else:
            gaps[rec['gate']]+=1
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
            'g18IntentionallyNotSelectedNotMissingSource':g18_intentionally_not_selected,
            'unresolvedG0ResearchBranchCount':len(unresolved_branch_analyses),
            'unresolvedG0PlayerSourceChecks':sum(x['masterAndOverlayChecks']
                    for x in unresolved_branch_analyses),
            'unresolvedG0ResearchDoesNotSelect':True,
            'unresolvedG0ResearchExamples':unresolved_branch_analyses[:20],
            'uniqueGameSurvivors':len(qualified),
            'g16FinalistCompetition':g16_receipt,
            'preCoreQualifiedSurvivors':all_survivor_receipts,
            'gameSurvivorPool':_finish_pool(games,game_pool,card,g16_receipt),
            'nonselectedGameResearchNotes':nonselected_game_notes,
            'nonselectedGameResearchNeverReplacesLockedCore':True,
            'retroactiveCardMutation':False,
            'errors':errors,'scan':scan}
    log_job(con,f'{date}-{stage}',date,stage,'COMPLETE' if card else 'INPUT_INCOMPLETE',
            {k:v for k,v in result.items() if k not in ('card','scan')})
    return result