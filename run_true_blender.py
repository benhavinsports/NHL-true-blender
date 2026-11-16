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
from nhl_true_blender_engine.lineup_parser import fetch_and_ingest_lineups
from nhl_true_blender_engine.historical_shots import collect_history
from nhl_true_blender_engine.edge_live import collect_edge, review_g0_goalie_origins
from nhl_true_blender_engine.edge_derived_routes import derive_nhl_edge_attacks
from nhl_true_blender_engine.goalie_history_fallback import collect_goalie_pbp_fallback
from nhl_true_blender_engine.official_context import collect_context
from nhl_true_blender_engine.contradiction_review import review_all_candidates
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

async def run(date, stage, state_dir="state", output_dir="runs"):
    state = Path(state_dir)
    output = Path(output_dir)
    state.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    con = open_db(str(state / "true_blender.sqlite"))
    try:
        async with _Client() as client:
            snapshot = await official_slate(client, date, con)
            historical = await collect_history(client, con, snapshot, date, stage)
            context_research = await collect_context(client, con, snapshot, date, stage)
            edge_research = await collect_edge(client, con, snapshot, date, stage)
            season_goal_research = await collect_season_goal_history(client, con, snapshot, date, stage)
            goal_tracking = {'status': 'DISABLED_BY_DEFAULT', 'reason': 'Historical sprite archive is supplemental, not G0 anatomical evidence'}
            if os.environ.get('ENABLE_GOAL_SPRITES') == '1':
                goal_tracking = await collect_goal_sprites(client, snapshot, date, max_goals=12)
        source_research = await collect_secondary(con, snapshot, date, stage)
        source_research['parsedLineups']=await fetch_and_ingest_lineups(
            con,snapshot,date,stage)
        csv_dir = os.environ.get('MONEYPUCK_CSV_DIR')
        if csv_dir and Path(csv_dir, 'skaters.csv').exists():
            source_research['moneypuck'] = import_moneypuck(
                con, snapshot, date, stage, csv_dir,
                os.environ.get('MONEYPUCK_EXPORT_ASOF'))
        # Starters and projected lines are attached before independently
        # measured EDGE comparisons; a skater is never picked before full G0.
        attach(con, snapshot, date, stage)
        derived_routes = derive_nhl_edge_attacks(con, snapshot, date, stage)
        attach(con, snapshot, date, stage)
        # Goalie-first fallback requires the exact independently sourced
        # expected/confirmed starter identity from the parsed lineup report.
        # NHL EDGE sometimes lacks qualifying current-season origin data.
        # Reconstruct goalie-specific previous-game NHL PBP (not rink-to-net
        # anatomy) BEFORE G0 chooses an attack side. Never pick by absence
        # of the opponent's profile.
        async with _Client() as client:
            goalie_pbp_fallback = await collect_goalie_pbp_fallback(
                client,con,snapshot,date,stage)
        source_research['independentGoaliePbpFallback']=goalie_pbp_fallback
        attach(con, snapshot, date, stage)
        scouting_path = os.environ.get('GOALIE_SCOUTING_JSON')
        if scouting_path:
            source_research['goalieScouting'] = ingest_scouting(
                con, snapshot, date, stage, scouting_path)
            attach(con, snapshot, date, stage)
        initial_watch = await collect_watch(None, con, date, snapshot)
        edge_g0_review = review_g0_goalie_origins(con, snapshot, date, stage)
        contradiction_research = review_all_candidates(con, snapshot, date, stage)
        attach(con, snapshot, date, stage)
        result = execute(con, snapshot, date, stage)
        result['firstNonpassingGateAudit']=first_gate_audit(con,date,stage)
        result['gateCertification']=certify_gates(con,date,stage,result.get('games'))
        result['dashboardExport']=export_dashboard(con,date,stage,snapshot,state)
        diagnostic = explain_live_blockers(con,date,stage)
        diag_path = state / 'site_runs' / f'{date}-gate-diagnostics.json'
        diag_path.parent.mkdir(parents=True, exist_ok=True)
        diag_path.write_text(json.dumps(diagnostic, indent=2, default=str), encoding='utf-8')
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
        result['g0RinkOriginResearch']=edge_g0_review
        result['g0OfficialPbpFallback']=goalie_pbp_fallback
        # Source-verified Core JSON is produced independently by the engine.
        # GitHub Actions commits it under state/; GitHub Pages publishes
        # the authoritative card and run receipt via site/data/latest.json.
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
            "missingByGate": result["missingByGate"],
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
