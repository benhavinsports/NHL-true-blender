"""Standalone GitHub Actions entrypoint for the integrated G0–G18 engine.

Uses official NHL schedule/rosters and previously sourced evidence in persistent
SQLite. Missing independent goalie/line/route evidence is reported, not invented.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from nhl_true_blender_engine.sources import NHLClient, official_slate, collect_watch
from nhl_true_blender_engine.enrichment import attach
from nhl_true_blender_engine.secondary_sources import collect_secondary
from nhl_true_blender_engine.lineup_parser import fetch_and_ingest_lineups, fetch_and_ingest_additional_deployment
from nhl_true_blender_engine.edgehalla_deployment import collect_edgehalla_deployment
from nhl_true_blender_engine.historical_shots import collect_history
from nhl_true_blender_engine.edge_live import collect_edge, review_g0_goalie_origins
from nhl_true_blender_engine.dated_goalie_projections import collect_dated_goalie_projections
from nhl_true_blender_engine.dfo_dated_starters import collect_dfo_goalies
from nhl_true_blender_engine.edge_derived_routes import derive_nhl_edge_attacks
from nhl_true_blender_engine.goalie_history_fallback import collect_goalie_pbp_fallback
from nhl_true_blender_engine.official_dressed import collect_official_dressed
from nhl_true_blender_engine.official_context import collect_context
from nhl_true_blender_engine.first_gate_audit import first_gate_audit
from nhl_true_blender_engine.gate_input_diagnostics import explain_live_blockers
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.dashboard_export import export_dashboard
from nhl_true_blender_engine.moneypuck_import import import_moneypuck
from nhl_true_blender_engine.scouting_import import ingest_scouting
from nhl_true_blender_engine.goal_tracking import collect_goal_sprites
from nhl_true_blender_engine.season_goal_history import collect_season_goal_history
import httpx
from datetime import timezone
from nhl_true_blender_engine.engine import execute, MASTER, OVERLAY
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.source_recovery import recovery_snapshot, pregame_only_snapshot

async def run(date, stage, state_dir="state", output_dir="runs"):
    state = Path(state_dir)
    output = Path(output_dir)
    state.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    con = open_db(str(state / "true_blender.sqlite"))
    try:
        async with _Client() as client:
            snapshot = await official_slate(client, date, con)
            cycle_now=datetime.now(timezone.utc)
            pregame_snapshot=pregame_only_snapshot(snapshot,cycle_now)
            print(
                f"BLENDER official slate loaded: {date}; "
                f"games={len(snapshot.get('games', []))}; "
                f"still_pregame={len(pregame_snapshot.get('games', []))}",
                flush=True)
            print("BLENDER collecting official history and goalie peer evidence", flush=True)
            historical = await collect_history(client, con, pregame_snapshot, date, stage)
            # This event payload is an in-memory input to the later goalie
            # fallback, not a JSON report or persistent duplicate database.
            league_goalie_peer_events=historical.pop("_goaliePeerPbpEvents",[])
            context_research = await collect_context(client, con, pregame_snapshot, date, stage)
            edge_research = await collect_edge(client, con, pregame_snapshot, date, stage)
            season_goal_research = await collect_season_goal_history(client, con, pregame_snapshot, date, stage)
            goal_tracking = {'status': 'DISABLED_BY_DEFAULT', 'reason': 'Historical sprite archive is supplemental, not G0 anatomical evidence'}
            if os.environ.get('ENABLE_GOAL_SPRITES') == '1':
                goal_tracking = await collect_goal_sprites(client, pregame_snapshot, date, max_goals=12)
        print("BLENDER collecting secondary sources, lineups, deployment and projected starters", flush=True)
        source_research = await collect_secondary(con, pregame_snapshot, date, stage)
        source_research['parsedLineups']=await fetch_and_ingest_lineups(
            con,pregame_snapshot,date,stage)
        source_research['additionalStructuredDeployment']=await fetch_and_ingest_additional_deployment(
            con,pregame_snapshot,date,stage)
        source_research['datedEdgehallaProjection']=await collect_edgehalla_deployment(
            con,pregame_snapshot,date,stage)
        # Independent dated NHL.com projected goalie listings are researched
        # rather than treating ambiguous generic EXPECTED branches as final.
        # These do not claim team confirmation or overwrite confirmed goalies.
        from nhl_true_blender_engine.nhl_projected_goalies import collect_nhl_projected_goalies
        source_research['officialNhlProjectedGoalies']=await collect_nhl_projected_goalies(
            con,pregame_snapshot,date,stage)
        # The primary third-party markdown sometimes still contains YESTERDAY's
        # header at sunrise; do not stop G0 for all 11 current-day games.
        # Collect dated, matchup-scoped projected goalie IDs from an additional
        # public source. Preserve EXPECTED/PROJECTED vs CONFIRMED and require
        # exact official NHL roster ID matching before using any branch.
        source_research['datedGoalieProjections']=await collect_dated_goalie_projections(
            con,pregame_snapshot,date,stage)
        source_research['datedIndependentStartingGoalies']=await collect_dfo_goalies(
            con,pregame_snapshot,date,stage)
        async with _Client() as client:
            source_research['officialPregameDressed']=await collect_official_dressed(
                client,con,pregame_snapshot,date,stage)
        csv_dir = os.environ.get('MONEYPUCK_CSV_DIR')
        if csv_dir and Path(csv_dir, 'skaters.csv').exists():
            source_research['moneypuck'] = import_moneypuck(
                con, pregame_snapshot, date, stage, csv_dir,
                os.environ.get('MONEYPUCK_EXPORT_ASOF'))
        # Starters and projected lines are attached before independently
        # measured EDGE comparisons; a skater is never picked before full G0.
        print("BLENDER attaching collected evidence and deriving source-supported attack routes", flush=True)
        attach(con, snapshot, date, stage)
        derived_routes = derive_nhl_edge_attacks(con, pregame_snapshot, date, stage)
        attach(con, snapshot, date, stage)
        # Goalie-first fallback requires the exact independently sourced
        # expected/confirmed starter identity from the parsed lineup report.
        # NHL EDGE sometimes lacks qualifying current-season origin data.
        # Reconstruct goalie-specific previous-game NHL PBP (not rink-to-net
        # anatomy) BEFORE G0 chooses an attack side. Never pick by absence
        # of the opponent's profile.
        async with _Client() as client:
            goalie_pbp_fallback = await collect_goalie_pbp_fallback(
                client,con,pregame_snapshot,date,stage,
                league_peer_events=league_goalie_peer_events)
        source_research['independentGoaliePbpFallback']=goalie_pbp_fallback
        attach(con, snapshot, date, stage)
        scouting_path = os.environ.get('GOALIE_SCOUTING_JSON')
        if scouting_path:
            source_research['goalieScouting'] = ingest_scouting(
                con, pregame_snapshot, date, stage, scouting_path)
            attach(con, snapshot, date, stage)
        initial_watch = await collect_watch(None, con, date, pregame_snapshot)
        edge_g0_review = review_g0_goalie_origins(con, pregame_snapshot, date, stage)
        # Independent contradiction evidence is reviewed at G17, not after G0.
        attach(con, snapshot, date, stage)
        print("BLENDER executing original G0-G18 and overlay", flush=True)
        result = execute(con, snapshot, date, stage, now=cycle_now)
        print(f"BLENDER first gate execution complete; Core present={bool(result.get('card'))}", flush=True)
        contradiction_research = result.get('g17ReviewSummary')
        # Keep searching every still-pre-puck game at its first
        # nonpassing original gate. A source returning no usable observation
        # is not a terminal result: the next complete refresh searches again.
        # The only per-game end condition is the original puck-drop freeze.
        # One authoritative workflow cycle performs the full source collection,
        # executes the original G0-G18 engine, records its current evidence state,
        # and returns so the canonical ledger can be saved and Pages refreshed.
        # The serialized five-minute schedule starts the next full source cycle.
        # There is no total retry limit: every scheduled cycle continues researching
        # unresolved games until recovery_snapshot applies each game's puck-drop freeze.
        feedback=[]
        remaining_snapshot=recovery_snapshot(con,snapshot,date,stage,result,now=cycle_now)
        remaining_ids=[str(g['id']) for g in remaining_snapshot['games']]
        if remaining_ids:
            feedback.append({
                'cycleCheckpoint':True,
                'researchedGameIds':[str(g['id']) for g in pregame_snapshot.get('games',[])],
                'remainingPregameGameIdsAfterRefresh':remaining_ids,
                'nextScheduledCycleContinuesSourceRecovery':True,
                'noAutomaticPasses':True
            })
        print(
            f"BLENDER cycle complete: {len(remaining_ids)} unresolved pregame games "
            "will receive another full source refresh on the next scheduled cycle; "
            f"Core present={bool(result.get('card'))}",
            flush=True
        )
        result['evidenceFeedbackLoop']=feedback
        result['firstNonpassingGateAudit']=first_gate_audit(con,date,stage)
        result['gateCertification']=certify_gates(con,date,stage,result.get('games'))
        result['dashboardExport']=export_dashboard(con,date,stage,snapshot,state)
        diagnostic = explain_live_blockers(con,date,stage)
        # Compact, stage-specific ROOT CAUSE evidence for the actual G0-
        # selected roster only. The large diagnostic matrix is retained in
        # full, but aggregating its intersections makes it possible to
        # repair source failures without visually sorting or picking skaters.
        # This is NOT a replacement Core, ranking or scoring shortcut.
        from collections import Counter
        real=[row for row in diagnostic.get('candidateGateMatrix',[])
              if row.get('masterDispositions',{}).get('G0')=='PASS'
              and not str(row.get('playerId','')).startswith('G0_RESEARCH:')]
        overlapping=Counter()
        gate_causes=Counter()
        samples={}
        for row in real:
            gates=tuple(row.get('failedMasterGates') or ())
            steps=tuple(row.get('failedOverlayGates') or ())
            overlapping[(gates,steps)]+=1
            for gate in gates+steps:
                # G18 is final Core assembly, not another data acquisition
                # gate. Preserve its individual disposition in the full
                # matrix, but do not call non-Core decisions source blockers.
                if gate=="G18":
                    continue
                gate_causes[gate]+=1
                # Source-grounded example, not a skater shortlist.
                if gate not in samples:
                    samples[gate]={'gameId':row['gameId'],
                                   'playerId':row['playerId'],
                                   'reason':(row.get('nonpassReasons') or {}).get(gate)}
        blocker_summary={
            'slateDate':date,'stage':stage,
            'g0AcceptedSkaterMatrices':len(real),
            'g0RejectedResearchNeverCountsAsCandidate':True,
            'allGatesExecutedButNotAllPassed':True,
            'notScorerSelectionOrRanking':True,
            'fullActualCandidateGateMatrixStoredSeparately':True,
            'nonpassingGateCounts':dict(gate_causes),
            'g18NonselectedNotMissingSource':
                result.get('g18IntentionallyNotSelectedNotMissingSource',0),
            'g18ActualMissingSourceCount':
                result.get('missingByGate',{}).get('G18',0),
            'g18FinalCoreAssemblyNotSourceCollection':True,
            'exactFailedGateIntersections':[{
                'masterGates':list(master),'overlaySteps':list(overlay),
                'playerCount':count}
                for (master,overlay),count in
                sorted(overlapping.items(),key=lambda item:(-item[1],str(item[0])))],
            'oneObservedEvidenceExamplePerGate':samples,
        }
        diag_root=state/'site_runs'
        diag_root.mkdir(parents=True,exist_ok=True)
        (diag_root/f'{date}-{stage.lower()}-blocker-summary.json').write_text(
            json.dumps(blocker_summary,indent=2,default=str),encoding='utf-8')
        # Save the complete diagnostic as ONE lossless gzip file.
        # GitHub's 100 MB limit applies to the saved compressed file.
        import gzip
        diag_path=state/'site_runs'/f'{date}-{stage.lower()}-gate-diagnostics.json.gz'
        diag_path.parent.mkdir(parents=True,exist_ok=True)
        original=json.dumps(diagnostic,indent=2,default=str).encode('utf-8')
        archived=gzip.compress(original,compresslevel=9,mtime=0)
        if len(archived)>=100_000_000:
            raise ValueError(
                f'Compressed full gate diagnostic is {len(archived)} bytes; '
                'GitHub file limit is 100,000,000 bytes')
        if gzip.decompress(archived)!=original:
            raise ValueError('Full gate diagnostic compression verification failed')
        diag_path.write_bytes(archived)
        result['officialBoxscoreCoverage']=historical.get('boxscoreGoalLogReconciliation',{})
        result['officialSeasonGoalHistoryCoverage']=season_goal_research
        result['g17CrossSourceReviews']=contradiction_research
        result['officialDefenseCoverage']=historical.get('defensiveCoverage',{})
        result['historicalShiftCoverage']=historical.get('historicalDefensiveShiftCoverage',{})
        result['derivedRouteCoverage']={k:derived_routes.get(k) for k in (
            'method','goalieProfilesWithMeasuredWeakOrigins','ownSkaterRoutes',
            'unresolvedCount','anatomicalWeaknessCertified','explicitlyInferred')}
        result['edgeSourceCoverage']={k:edge_research.get(k) for k in (
            'status','allCurrentRosterIdentitiesChecked','goalieRinkProfiles',
            'skaterRinkProfiles','totalFailed','anatomicalClaimCertified')}
        result['lineupSourceCoverage']={k:source_research.get('parsedLineups',{}).get(k)
            for k in ('status','deploymentRecords','goalieReports','error')}
        # Every G6 source collector must publish its actual parsing/freshness
        # outcome. Previously the site showed only the stale primary markdown
        # failure, hiding NHL.com, structured alternatives and Edgehalla.
        # This is a source-coverage audit, NEVER a selection or gate override.
        structured=source_research.get('additionalStructuredDeployment') or {}
        result['additionalStructuredDeploymentCoverage']={
            'deploymentRecords':structured.get('deploymentRecords',0),
            'unmatchedCount':len(structured.get('unmatched') or []),
            'skippedCount':len(structured.get('skipped') or []),
            'teamReports':{
                team:{
                    'status':report.get('status'),
                    'conflictCount':report.get('conflictCount'),
                    'lineEvidenceFound':report.get('lineEvidenceFound'),
                    'powerPlayEvidenceFound':report.get('powerPlayEvidenceFound'),
                    'sources':[{
                        'provider':entry.get('source') or entry.get('provider'),
                        'url':entry.get('url'),
                        'sourceDate':entry.get('sourceDate'),
                        'dateVerified':entry.get('dateVerified'),
                        'errors':(entry.get('errors') or [])[:2],
                        'result':entry.get('result'),
                    } for entry in (report.get('attempts') or [])[:7]],
                    'error':report.get('error'),
                } for team,report in (structured.get('sources') or {}).items()
            },
            'noUndatedRolePromoted':True,
        }
        edge_deployment=source_research.get('datedEdgehallaProjection') or {}
        result['datedEdgehallaProjectionCoverage']={
            'status':edge_deployment.get('status'),
            'deploymentRecords':edge_deployment.get('deploymentRecords',0),
            'teams':edge_deployment.get('teams',[]),
            'neverConfirmed':edge_deployment.get('neverConfirmed',True),
        }
        official_nhl_lineups=source_research.get('officialNhlProjectedGoalies') or {}
        result['officialNhlProjectedLineupCoverage']={
            'status':official_nhl_lineups.get('status'),
            'officialProjectedEVReceipts':official_nhl_lineups.get(
                'officialProjectedEVReceipts',0),
            'projectedGoalieReceipts':official_nhl_lineups.get(
                'projectedGoalieReceipts',0),
            'officialLineupNeverPromotedToConfirmed':official_nhl_lineups.get(
                'officialLineupNeverPromotedToConfirmed',True),
            'sourceAttempts':[{
                'url':item.get('url'),
                'status':item.get('status'),
                'error':item.get('error'),
            } for item in (official_nhl_lineups.get('sourceAttempts') or [])],
        }
        result['datedGoalieSourceCoverage']=source_research.get(
            'datedGoalieProjections',{})
        # Persist parser/source diagnostics so G0 cannot silently remain
        # ambiguous when the additional dated source failed or conflicted.
        # Read-only evidence: never a gate verdict or goalie confirmation.
        result['datedIndependentGoalieSourceCoverage']=source_research.get(
            'datedIndependentStartingGoalies',{})
        result['g0RinkOriginResearch']=edge_g0_review
        result['g0OfficialPbpFallback']=goalie_pbp_fallback
        # Source-verified Core JSON is produced independently by the engine.
        # GitHub Actions commits it under state/; GitHub Pages publishes
        # the authoritative card and run receipt via site/data/latest.json.
        print("BLENDER writing this cycle's evidence, card receipt and dashboard checkpoint", flush=True)
        from scripts.publish_site_state import export_run
        site_export = export_run(con, date, stage, result, state_dir)
        summary = {k: v for k, v in result.items() if k != "scan"}
        summary['sitePublication'] = site_export
        summary.update({
            "officialSource": snapshot.get("officialSource"),
            "secondarySourceResearch": source_research,
            "historicalShotResearch": historical,
            "actualDefensiveShiftResearch": historical.get('historicalDefensiveShiftCoverage',{}),
            "officialVenueRestContext": context_research,
            "officialFullSeasonGoalHistory": season_goal_research,
            "officialEdgeRinkZoneEvidence": edge_research,
            "edgeDerivedShotOriginMechanisms": derived_routes,
            "g0RinkAreaGoalieComparison": edge_g0_review,
            "goalieHistoricalOfficialPbpFallback": goalie_pbp_fallback,
            "sourceLinkedG17ContradictionReviews": contradiction_research,
            "automaticPregameWatch": initial_watch,
            "historicalGoalTracking": goal_tracking,
            "collectionErrors": snapshot.get("collectionErrors", []),
            "masterGateOrder": MASTER,
            "overlayGateOrder": OVERLAY,
            "fullSelectionEngine": "nhl_true_blender_engine.engine.execute",
            "validatedCorePublished": bool(result.get("card")),
        })
        path = output / f"true_blender_{date}_{stage.lower()}.json"
        path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        print(json.dumps({
            "output": str(path), "games": result["games"],
            "eligibleSkaters": result["eligibleSkaterRows"],
            "gateRows": result["gateRows"],
            "g0Complete": result["g0Complete"],
            "g0Directions": result["g0Directions"],
            # The missing-evidence counts are displayed in canonical gate
            # sequence, not in the order missing records happened to arrive.
            "gateExecutionOrder": result.get("gateExecutionOrder", MASTER),
            "missingByGate": result["missingByGate"],
            "firstNonpassingGateCounts": {
                gate: result.get("firstNonpassingGateAudit", {})
                    .get("firstNonpassingGateCounts", {}).get(gate, 0)
                for gate in MASTER
                if result.get("firstNonpassingGateAudit", {})
                    .get("firstNonpassingGateCounts", {}).get(gate, 0)
            },
            "corePublished": bool(result.get("card")),
            "edgeCollectedSkaters":edge_research.get("skaterRinkProfiles",0),
            "edgeCollectedGoalies":edge_research.get("goalieRinkProfiles",0),
            "lineupEvidence":source_research.get("parsedLineups",{}),
            "errors": result["errors"][:10],
        }, indent=2))
        return summary
    finally:
        con.close()

class _Client:
    async def __aenter__(self):
        self.client = NHLClient()
        return self.client
    async def __aexit__(self, *args):
        await self.client.close()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date")
    p.add_argument("--mode", choices=["projected", "confirmed"], default="projected")
    args = p.parse_args()
    date = args.date or datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    datetime.strptime(date, "%Y-%m-%d")
    asyncio.run(run(date, args.mode.upper()))

if __name__ == "__main__":
    main()

