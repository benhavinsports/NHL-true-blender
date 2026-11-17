"""Export independently source-verified Core and run JSON for GitHub Pages.

GitHub Actions commits state/site_cards and state/site_runs. The separate
Deploy Pages workflow packages their authoritative result in
site/data/latest.json. This transport never picks or substitutes scorers.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from nhl_true_blender_engine.engine import MASTER, OVERLAY, STEPS_BY_GATE
from nhl_true_blender_engine.storage import fingerprint
from nhl_true_blender_engine.core_identity import expected_core_ids

class PublicationConflict(RuntimeError):
    pass

def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)

def _active_saved_card(path):
    """A retracted old G18 card is an audit record, never a live Core."""
    if not path.exists():
        return None
    old=json.loads(path.read_text(encoding='utf-8'))
    if (old.get('verified') is False
            and old.get('status')=='RETRACTED_UNAUTHORIZED_G18'):
        return None
    return old


def _was_explicitly_retracted(path, root, slate_date):
    if not path.exists():
        return False
    doc=json.loads(path.read_text(encoding='utf-8'))
    if doc.get('verified') is not False or doc.get('status')!='RETRACTED_UNAUTHORIZED_G18':
        return False
    manifest=root/'core_retractions'/f'{slate_date}.json'
    if not manifest.is_file():
        raise PublicationConflict('Retracted Core missing immutable original archive')
    proof=json.loads(manifest.read_text(encoding='utf-8'))
    if proof.get('cardId')!=doc.get('cardId') or proof.get('originalFingerprint')!=doc.get('fingerprint'):
        raise PublicationConflict('Retraction original fingerprint or card ID mismatch')
    return True



def _unresolved_first_gate_source_receipts(con, date, stage, game_pool):
    """Compact TRUE gate receipts needed to repair an unresolved game.

    Selection does not consult this review. Copy only the original
    source-grounded evidence of the furthest still-blocked candidate and
    exact raw source IDs; never infer a PASS, create a Core or skip a gate.
    Unlike the 9-MB candidate matrix this can be checked in saved JSON.
    """
    wanted=('G0','G4','G9','G10','G15')
    out=[]
    for game in game_pool or []:
        if game.get('status')=='SURVIVOR':
            continue
        furthest=game.get('furthestCandidatesDiagnosticOnly') or []
        item={'gameId':game.get('gameId'),'matchup':game.get('matchup'),
              'stop':game.get('stoppedAt'),'status':game.get('status'),
              'nonSelectionDiagnosticOnly':True}
        if not furthest:
            out.append(item)
            continue
        candidate=furthest[0]
        pid=str(candidate.get('playerId') or '')
        item.update({'candidateId':pid,'candidateName':candidate.get('player'),
                     'candidateStoppedAt':candidate.get('stoppedAt')})
        proof={}
        for gate in wanted:
            row=con.execute(
                "SELECT disposition,details,evaluated_at FROM gates WHERE slate_date=? "
                "AND stage=? AND game_id=? AND player_id=? AND gate=?",
                (date,stage,str(game.get('gameId')),pid,gate)).fetchone()
            if not row:
                proof[gate]={'status':'NOT_RECORDED'}
                continue
            details=json.loads(row['details'] or '{}')
            ev=details.get('evidence') or {}
            if gate=='G15':
                fields=('independentHistoricalGoalFinishingEvidence',
                    'goalSourceReconciledToDatedAppearances',
                    'separateOfficialShotOriginSource',
                    'officialOwnedGoalsInMatchedOrigin',
                    'officialDatedSeasonGoals',
                    'seasonAndReleaseGoalCreditsConsistent',
                    'independentSeasonLogSource',
                    'semanticProofGaps')
            elif gate=='G9':
                fields=('shooterZone','greenTarget','redAvoid','zoneConcessionEvidence',
                        'coverageSourceType','coverageComparison','semanticProofGaps')
            elif gate=='G10':
                fields=('historicalDirectGoalRecipientVerified',
                        'historicalDirectGoalRecipientVerificationMethod',
                        'semanticProofGaps')
            elif gate=='G0':
                fields=('targetGoalie','branchStatus','directionSelectedBeforeSkaters',
                        'weakZones','semanticProofGaps')
            else:
                fields=('archetype','ownRelease','semanticProofGaps')
            proof[gate]={'status':row['disposition'],
                'evidence':{k:ev[k] for k in fields if k in ev},
                'sourceUrls':[v for v in (details.get('sourceIds') or [])
                              if isinstance(v,str) and v.startswith('https://')][:5]}
        item['recordedOriginalGateEvidence']=proof
        out.append(item)
    return out


def _before_puck(when, start):
    """Only time-stamped original decisions strictly before this game's puck drop."""
    try:
        a=datetime.fromisoformat(str(when).replace('Z','+00:00'))
        b=datetime.fromisoformat(str(start).replace('Z','+00:00'))
        return a.tzinfo is not None and b.tzinfo is not None and a<b
    except (TypeError,ValueError):
        return False

def _public_survivor_gate_cards(con, slate_date, stage, pool):
    """Read-only compact actual gate receipts for every saved game survivor.

    The dashboard never certifies, replaces, or selects a scorer. Copy each
    original gate disposition from the database, and fail closed on missing
    rows. Trim large telemetry arrays so Pages stays light on mobile.
    """
    visible={
      'G0':('selectedAttacker','selectedDefender','attacker','targetGoalie',
            'branchStatus','directionSelectedBeforeSkaters','weakZones'),
      'G1':('venueRestTravel',),
      'G2':('availability','position','fullPoolSize'),
      'G3':('goalieWeakZones','goalieSample'),
      'G4':('archetype','ownRelease'),
      'G5':('shooterZone','weakZones','goalieStrengthZones'),
      'G6':('deployment',),
      'G7':('distinctGoalDates','positiveDatedShotAppearances'),
      'G8':('contextSourceType','independentContextReview'),
      'G9':('shooterZone','greenTarget','redAvoid','zoneConcessionEvidence'),
      'G10':('historicalDirectGoalRecipientVerified',
             'historicalDirectGoalRecipientVerificationMethod'),
      'G10.5':('comparisonRows','allAlternativesScanned'),
      'G11':('shotContinuation',),
      'G12':('officialGoalCreditsReconciled','datedScoringReconciliation'),
      'G13':('name','jersey','date'),
      'G14':('whoAnomalyPhysicallySupported',),
      'G15':('officialOwnedGoalsInMatchedOrigin','officialDatedSeasonGoals',
             'matchedOriginOwnOnNetShots','matchedOriginHasHistoricalGoal',
             'fullSeasonGoalCreditsReconciledAgainstEdgeOrigins',
             'totalOwnedGoalsFromEveryNhlEdgeOrigin',
             'directFinisherEvidenceMethod'),
      'G16':('everyOtherActiveTeammate','includesDepthAndDefense',
             'crossGameFinalistCompetitionRunsAfterEveryGame'),
      'G17':('sourceDerivedReviewResolved','goalieBranch'),
      'G18':('pathClassificationEvidence','G16FinalistDecision',
             'G18CoreSlotGrantedOnlyAfterG16'),
    }
    collected={}
    for game in pool or []:
        if game.get('status')!='SURVIVOR' or not game.get('survivor'):
            continue
        survivor=game['survivor']
        game_id=str(game.get('gameId') or '')
        player_id=str(survivor.get('playerId') or '')
        if not game_id or not player_id:
            continue
        rows=[]
        for gate in MASTER:
            record=con.execute(
                "SELECT disposition,details,evaluated_at FROM gates WHERE slate_date=? "
                "AND stage=? AND game_id=? AND player_id=? AND gate=?",
                (slate_date,stage,game_id,player_id,gate)).fetchone()
            if not record:
                rows.append({'gate':gate,'status':'NO_RECORDED_DECISION',
                             'prePuckRecord':False,'sourceIds':[], 'evidence':{}})
                continue
            try:
                original=json.loads(record['details'] or '{}')
            except (TypeError,ValueError):
                original={}
            evidence=original.get('evidence') or {}
            scoped={k:evidence[k] for k in visible[gate] if k in evidence}
            if gate=='G4' and isinstance(scoped.get('ownRelease'),dict):
                scoped['ownRelease']={k:scoped['ownRelease'][k]
                    for k in ('zone','ownedGoals','attempts','sourceType')
                    if k in scoped['ownRelease']}
            if gate=='G10.5':
                scoped['comparisonRows']=[
                    {k:row[k] for k in ('status','challengerId')
                     if k in row}
                    for row in (evidence.get('comparisonRows') or [])]
            if gate=='G18' and isinstance(scoped.get('pathClassificationEvidence'),dict):
                p=scoped['pathClassificationEvidence']
                scoped['pathClassificationEvidence']={k:p[k]
                    for k in ('path','scoringLane','rationale')
                    if k in p}
            nested=evidence.get('originalFunctionEvidence') or []
            rows.append({'gate':gate,'status':record['disposition'],
                # This is a display receipt, not an assertion that a
                # missing source or post-puck row may be called pre-puck.
                'prePuckRecord':_before_puck(record['evaluated_at'],
                    game.get('gameStartUTC')),
                'sourceIds':list(dict.fromkeys(
                    x for x in original.get('sourceIds',[])
                    if isinstance(x,str) and x.startswith('https://')))[:10],
                'evidence':scoped,
                'originalFunctions':[{
                    'step':fn.get('step'),'status':fn.get('disposition')}
                    for fn in nested if isinstance(fn,dict)]})
        collected[game_id+':'+player_id]=rows
    return collected

def export_run(con, slate_date, stage, result, root='state'):
    root = Path(root)
    card = result.get('card')
    status_path = root / 'site_runs' / f'{slate_date}.json'
    status = {
        'slateDate':slate_date, 'stage':stage,
        'runner':'GITHUB_ACTIONS_AUTONOMOUS',
        'updatedUTC':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'games':result.get('games',0),
        'g0Directions':result.get('g0Directions',0),
        'g0Complete':result.get('g0Complete',0),
        # Distinguish real G0-authorized candidate matrix checks from
        # branch-specific research on official skaters whose attack side
        # has NOT passed G0. Both are retained, but only the former enter
        # the Core selection/certification denominator.
        'eligibleSkaterRows':result.get('eligibleSkaterRows',0),
        'coreEligibleSkaterMatrices':(result.get('gateCertification') or {}).get('scannedSkaters',0),
        'g0ResearchOnlyOfficialSkaters':(result.get('gateCertification') or {}).get('g0ResearchOnlyOfficialSkaters',0),
        'g0ResearchOnlyBranchMatrices':(result.get('gateCertification') or {}).get('g0ResearchOnlyBranchMatrices',0),
        'g0ResearchOnlyGateRows':(result.get('gateCertification') or {}).get('g0ResearchOnlyGateRows',0),
        'goalieResearchCannotBeCountedAsCertifiedCoreSkaters':True,
        'gateRows':result.get('gateRows',0),
        'missingByGate':result.get('missingByGate',{}),
        'g18IntentionallyNotSelectedNotMissingSource':
            result.get('g18IntentionallyNotSelectedNotMissingSource',0),
        'errors':result.get('errors',[])[:20],
        'nonselectedGameResearchNotes':result.get('nonselectedGameResearchNotes',[]),
        'nonselectedGameResearchIsDiagnosticOnly':True,
        'preCoreQualifiedSurvivors':result.get('preCoreQualifiedSurvivors',[]),
        'gameSurvivorPool':result.get('gameSurvivorPool',[]),
        'gameSurvivorGateReceipts':_public_survivor_gate_cards(
            con,slate_date,stage,result.get('gameSurvivorPool',[])),
        'sourceGateBlockerReceipts':_unresolved_first_gate_source_receipts(
            con,slate_date,stage,result.get('gameSurvivorPool',[])),
        'g16FinalistCompetition':result.get('g16FinalistCompetition'),
        'cardSavedByEngine':bool(card),
        'publishedToSite':False,
        'edgeSourceCoverage':result.get('edgeSourceCoverage',{}),
        'lineupSourceCoverage':result.get('lineupSourceCoverage',{}),
        'datedGoalieSourceCoverage':result.get('datedGoalieSourceCoverage',{}),
        'datedIndependentGoalieSourceCoverage':result.get('datedIndependentGoalieSourceCoverage',{}),
        'g0RinkOriginResearch':result.get('g0RinkOriginResearch',[]),
        'g0TwoGoalieDirectionDecisions':result.get('g0TwoGoalieDirectionDecisions',{}),
        'g0OfficialPbpFallback':result.get('g0OfficialPbpFallback',{}),
        'bothGoaliesRequiredBeforeG0PlayerElimination':True,
        'anatomicalEvidenceMisrepresented':False,
        'officialBoxscoreCoverage':result.get('officialBoxscoreCoverage',{}),
        'officialDefenseCoverage':result.get('officialDefenseCoverage',{}),
        'historicalShiftCoverage':result.get('historicalShiftCoverage',{}),
        'firstNonpassingGateAudit':result.get('firstNonpassingGateAudit',{}),
        'gateCertification':result.get('gateCertification',{}),
        'selectionFunnel':(result.get('gateCertification') or {}).get('selectionFunnel',{}),
        'survivorOnlyCertification':(result.get('gateCertification') or {}).get('selectedCoreOnlyFullyCertified'),
        'nonselectedGateAuditIsDiagnosticOnly':True,
    }
    # "Gate executed" and "player passed the gate" are distinct. Every
    # surveyed skater MUST have an ordered receipt for every gate, but rejected
    # skaters are expected to have ELIMINATED / NOT_EXECUTED source outcomes.
    # Those outcomes remain visible in missingByGate; they do not disqualify
    # fully proven surviving recipients. The recipient-specific checks below
    # independently enforce every original gate and its embedded functions.
    census=result.get('gateCertification') or {}
    scanned=census.get('scannedSkaters')
    attempts=census.get('gateChecksAttempted') or {}
    all_gates_attempted=(type(scanned) is int and scanned>0
        and all(attempts.get(gate)==scanned for gate in MASTER))
    full_execution=(
        all_gates_attempted
        and census.get('allSkatersHaveEachGateRecord') is True
        and census.get('allSkatersHaveExactExecutionOrder') is True
        and census.get('allOriginalFunctionsWereCheckedWithinGates') is True
        and census.get('copiedOverlayReceiptCount') == 0
        and census.get('twoDirectionsPerScheduledGameRecorded') is True
    )
    if not full_execution:
        prior=root/'site_cards'/f'{slate_date}.json'
        old=_active_saved_card(prior)
        status.update({
            'currentRunFullyCertified':False,
            'publishedToSite':False,
            'retainedOriginalLockedCard':bool(old),
            'cardId':old.get('cardId') if old else None,
            'publicationDecision':'FULL_GATE_EXECUTION_INCOMPLETE',
            'executionCertificationGaps':{
                'missingByGate':result.get('missingByGate',{}),
                'fullIndependentCardCertification':census.get('fullIndependentCardCertification'),
                'allGateChecksExecutedWithEvidence':census.get('allGateChecksExecutedWithEvidence'),
                'allSkatersHaveEachGateRecord':census.get('allSkatersHaveEachGateRecord'),
                'allSkatersHaveExactExecutionOrder':census.get('allSkatersHaveExactExecutionOrder'),
                'twoDirectionsPerScheduledGameRecorded':census.get('twoDirectionsPerScheduledGameRecorded'),
            },
        })
        _write(status_path,status)
        return status
    if not card:
        # Post-puck freeze is intentional: the selection engine may no longer
        # issue a new card even though today's ORIGINAL locked card is saved.
        # Do not erase or mark that frozen Core unpublished. Keep the prior
        # artifact unchanged, and distinguish an audit from a new selection.
        prior=root/'site_cards'/f'{slate_date}.json'
        locked=_active_saved_card(prior)
        if locked:
            # A historical card may remain immutable, but it cannot make a
            # newly failed Core assembly count as a successful fresh run.
            # Compare the complete pre-Core survivor set, not just the
            # subset that was previously locked.
            try:
                original=json.loads(locked.get('legsJson') or '[]')
            except (TypeError,ValueError):
                original=[]
            original_ids=[(str(x.get('gameId')),str(x.get('playerId')))
                          for x in original]
            # Compare with the survivors G16 actually retained for G18.
            qualified_ids=expected_core_ids({
                'preCoreQualifiedSurvivors':result.get('preCoreQualifiedSurvivors'),
                'g16FinalistCompetition':result.get('g16FinalistCompetition')}) or []
            mismatch=bool(qualified_ids and (
                len(qualified_ids)!=len(original_ids) or
                len(set(qualified_ids))!=len(qualified_ids) or
                set(qualified_ids)!=set(original_ids)))
            unresolved=any('PRE_CORE_REVIEW:' in str(x)
                           for x in (result.get('errors') or []))
            if mismatch or unresolved:
                status.update({
                    'cardId':locked.get('cardId'),
                    'publishedToSite':False,
                    'retainedOriginalLockedCard':True,
                    'currentRunFullyCertified':False,
                    'publicationDecision':'G18_UPSTREAM_SURVIVORS_UNRESOLVED',
                    'qualifiedSurvivorCount':len(qualified_ids),
                    'historicalLockedLegCount':len(original_ids),
                    'historicalCardIsNotCurrentRunCertification':True,
                })
            else:
                status.update({
                    'cardId':locked.get('cardId'),
                    'publishedToSite':True,
                    'retainedOriginalLockedCard':True,
                    'currentRunFullyCertified':bool(
                        (result.get('gateCertification') or {}).get('selectedCoreOnlyFullyCertified')),
                    'publicationDecision':'PRESERVED_FROZEN_CORE_NO_NEW_SELECTION',
                })
        else:
            status['publicationDecision']='NO_ELIGIBLE_G18_CARD'
            status['currentRunFullyCertified']=False
        _write(status_path,status)
        return status
    legs = card.get('current_legs') or []
    required_count = 2 if result.get('games')==2 else 3
    if len(legs)!=required_count or len({str(x.get('gameId')) for x in legs})!=required_count:
        raise PublicationConflict('Invalid G18 count or duplicate game')
    if card.get('fingerprint')!=fingerprint(legs):
        raise PublicationConflict('G18 card fingerprint mismatches its saved recipients')
    if result.get('g0Directions',0) < result.get('games',0):
        raise PublicationConflict('G0 game scan incomplete')
    required=set(MASTER)
    validation_gaps=[]
    for leg in legs:
        game_id, player_id = str(leg['gameId']),str(leg['playerId'])
        rows=con.execute("""SELECT gate, disposition, details FROM gates
               WHERE slate_date=? AND stage=? AND game_id=? AND player_id=?""",
               (slate_date,stage,game_id,player_id)).fetchall()
        trace={x['gate']:x for x in rows}
        if set(trace)!=required:
            validation_gaps.append({'gameId':game_id,'playerId':player_id,
                'missingGateRows':sorted(required-set(trace))})
            continue
        incomplete={g:x['disposition'] for g,x in trace.items() if x['disposition']!='PASS'}
        # The saved receipt is one G0–G18 trace. Each original function
        # is evidence inside the gate that owns it, never another gate row.
        function_gaps=[]
        for gate in MASTER:
            proof=json.loads(trace[gate]['details']).get('evidence') or {}
            nested=proof.get('originalFunctionEvidence') or []
            expected=STEPS_BY_GATE[gate]
            if [x.get('step') for x in nested]!=expected:
                function_gaps.append({'gate':gate,'reason':'MISSING_OR_REORDERED_ORIGINAL_FUNCTION'})
                continue
            for check in nested:
                evidence=check.get('evidence') or {}
                neutral=(check.get('step')=='Step13'
                         and evidence.get('nonblocking') is True)
                if (check.get('disposition')!='PASS' and not neutral
                    or evidence.get('independentOverlayEvaluation') is not True
                    or evidence.get('checkedBeforeG18') is not True
                    or evidence.get('masterGateVerdictCopied') is not False):
                    function_gaps.append({
                        'gate':gate,'function':check.get('step'),
                        'status':check.get('disposition'),
                        'reason':'ORIGINAL_FUNCTION_NOT_SOURCE_PROVEN'})
        if incomplete or function_gaps:
            validation_gaps.append({'gameId':game_id,'playerId':player_id,
                'notPassing':incomplete,'originalFunctionGaps':function_gaps})
            continue
        g0=json.loads(trace['G0']['details'])['evidence']
        if leg.get('opposingGoalieId') and str(g0.get('targetGoalie'))!=str(leg['opposingGoalieId']):
            raise PublicationConflict('G0 starter branch does not match final recipient')
        if any(not leg.get(k) for k in ('player','path','startUTC','sourceIds')):
            raise PublicationConflict('Recipient source or game-time field missing')
        if leg['path'] not in ('PRIMARY','TRANSFER','WHO'):
            raise PublicationConflict('Unsupported scorer path label')
    # Selected-recipient certification is the publication requirement:
    # nonselected players are allowed to fail or lack scorer evidence.
    # If the independent census exists, do not publish a new card when its
    # selected recipients have not all been genuinely verified.
    source_census=result.get('gateCertification') or {}
    if source_census and source_census.get('selectedCoreOnlyFullyCertified') is not True:
        validation_gaps.append({
            'reason':'SELECTED_CORE_INDEPENDENT_SOURCE_CERTIFICATION_FAILED',
            'selectedLegSourceGaps':source_census.get('selectedSourceAttributionGaps',[]),
            'selectedLegReviews':source_census.get('selectedLegs',[]),
        })
    # A newly missing independent overlay source cannot retroactively
    # overwrite or erase the previously frozen Core. Keep its immutable
    # JSON, record the exact current audit failure and do NOT claim that
    # the new run recertified the original card. No invented PASS/transfer.
    if validation_gaps:
        previous=root/'site_cards'/f'{slate_date}.json'
        retained=_active_saved_card(previous) is not None
        status.update({
            'currentRunFullyCertified':False,
            'independentOverlaySourceGaps':validation_gaps,
            'retainedOriginalLockedCard':retained,
            'publishedToSite':retained,
            'cardId':card['card_id'] if retained else None,
            'publicationDecision':'PRESERVED_ORIGINAL_WITH_AUDIT_GAPS' if retained
                                  else 'NEW_CARD_NOT_PUBLISHED_INCOMPLETE_OVERLAY',
        })
        _write(status_path,status)
        return status
    status['currentRunFullyCertified']=True
    status['publicationDecision']='SOURCE_CERTIFIED_AND_PUBLISHED'
    # Preserve the actual signed-by-ledger revision rationale in the saved
    # machine-readable card. The prior exporter silently left auditJson empty
    # even after a G18 replacement, making source/trigger history impossible
    # to inspect without opening the compressed SQLite ledger.
    version_row=con.execute(
        'SELECT created_at,rationale FROM card_versions '
        'WHERE slate_date=? AND revision=?',
        (slate_date,card['revision'])).fetchone()
    if not version_row:
        raise PublicationConflict('Canonical Core revision lacks saved replacement rationale')
    try:
        version_rationale=json.loads(version_row['rationale'])
        if not isinstance(version_rationale,dict):
            raise ValueError('Card version rationale is not an object')
    except (TypeError, ValueError):
        raise PublicationConflict('Canonical Core version rationale is invalid')
    rationale_audit=version_rationale.get('audit') or {}
    audit_receipt={
        'revision':card['revision'],
        'createdAt':version_row['created_at'],
        'type':version_rationale.get('type'),
        'rationale':version_rationale,
        'postRevisionTriggerChronologyVerified':(
            rationale_audit.get('triggerNewerThanBaselineVersion') is True
            if version_rationale.get('type')=='GATE_VALIDATED_REPLACEMENT'
            else None),
        'historicalReplacementPrecedesCurrentGuard':(
            version_rationale.get('type')=='GATE_VALIDATED_REPLACEMENT'
            and rationale_audit.get('triggerNewerThanBaselineVersion') is not True),
    }
    payload={
        'slateDate':slate_date,'cardId':card['card_id'],
        'stage':card['stage'],'status':'G18_SOURCE_VERIFIED',
        'source':'GITHUB_ACTIONS_FULL_GATE_MATRIX','verified':True,
        'fingerprint':card['fingerprint'],'revision':card['revision'],
        'originalFingerprint':fingerprint(card['initial_legs']),
        'legsJson':json.dumps(legs,sort_keys=True),
        'gradeJson':json.dumps(card.get('grade') or {}),
        'auditJson':json.dumps(audit_receipt,sort_keys=True,default=str),
        'provenance':'One original G0-G18 execution with embedded source-backed function evidence',
        'gateRows':result.get('gateRows'),
        'g0Directions':result.get('g0Directions'),
        'eligibleSkaterRows':result.get('eligibleSkaterRows'),
    }
    path=root/'site_cards'/f'{slate_date}.json'
    original_retracted=_was_explicitly_retracted(path,root,slate_date)
    # A discredited G18 card is not a baseline for a *new independent*
    # full-gate execution. Its complete original identity is archived under
    # core_retractions and SQLite card_retractions, never silently replaced.
    # Record issuance once, at the actual first publication. This is
    # provenance, never a reconstructed timestamp from a later grade/run.
    # A later confirmed pass may retain the original issuance but cannot
    # manufacture an earlier one for a legacy card.
    if path.exists() and not original_retracted:
        old=json.loads(path.read_text(encoding='utf-8'))
        if old.get('issuedAtUTC'):
            payload['issuedAtUTC']=old['issuedAtUTC']
        # Never erase a postgame grade during a late projected/confirmed
        # replay. The grade is attached to the immutable original card.
        if old.get('gradeJson') and json.loads(old['gradeJson'] or '{}'):
            if old.get('cardId')!=payload['cardId']:
                raise PublicationConflict('Cannot replay over a graded card')
            payload['gradeJson']=old['gradeJson']
            payload['auditJson']=old.get('auditJson','')
            payload['status']=old.get('status','FROZEN_GRADED')
        # Existing cards without a first-issuance receipt stay explicitly
        # unknown. Never backfill from a later confirmation or postgame run.
    else:
        issued=datetime.now(timezone.utc)
        from datetime import datetime as _dt
        starts=[_dt.fromisoformat(str(leg['startUTC']).replace('Z','+00:00'))
                for leg in legs]
        if any(issued>=start for start in starts):
            raise PublicationConflict(
                'First card publication occurred at/after a leg puck drop; '
                'refusing to invent a pre-puck issuance')
        payload['issuedAtUTC']=issued.isoformat(timespec='seconds')
    if path.exists() and not original_retracted:
        old=json.loads(path.read_text(encoding='utf-8'))
        if old.get('cardId')!=payload['cardId']:
            raise PublicationConflict('Different authoritative card ID already published')
        if old.get('fingerprint')!=payload['fingerprint']:
            versions=con.execute('''SELECT rationale FROM card_versions
                  WHERE slate_date=? AND revision>? ORDER BY revision''',
                  (slate_date,int(old.get('revision',1)))).fetchall()
            if not versions or not all(
                    json.loads(x['rationale']).get('type')=='GATE_VALIDATED_REPLACEMENT'
                    for x in versions):
                raise PublicationConflict('Scorer replacement missing verified G10.5/G17 version audit')
        order={'PROJECTED':0,'MIXED':1,'CONFIRMED':2}
        if order.get(payload['stage'],-1)<order.get(old.get('stage'),-1):
            raise PublicationConflict('Cannot demote already confirmed official card')
    _write(path,payload)
    status.update(publishedToSite=True,cardId=payload['cardId'],
                  fingerprint=payload['fingerprint'],cardPath=str(path))
    _write(status_path,status)
    return status
