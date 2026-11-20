"""Replay archived pregame bundles, optionally grading a separate ledger."""
import argparse
import asyncio
from collections import Counter
import hashlib
import json
import gzip
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from nhl_true_blender_engine.engine import execute, MASTER, OVERLAY
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.first_gate_audit import first_gate_audit
from nhl_true_blender_engine.gate_input_diagnostics import explain_live_blockers
from nhl_true_blender_engine.storage import open_db
from scripts.replay_postgame_grade import grade_frozen_legs


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('Evidence timestamps require a timezone')
    return result


def verified_bytes(root, path, digest):
    data = (root / path).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f'Hash mismatch: {path}')
    return data


def _event_dates(kind, payload):
    """Return explicit historical event dates, excluding slate/schedule as-of labels."""
    if kind == "GAME_SCHEDULE":
        return []
    found = set()
    if kind == "MATCH_CONTEXT":
        for key in ("awayLastGameDate", "homeLastGameDate"):
            value = payload.get(key)
            if isinstance(value, str):
                found.add(value[:10])
        return sorted(found)
    ignored = {
        "slateDate", "currentDate", "nextDate", "prevDate",
        "publishedAsOfSlateDate", "historicalSampleAsOf",
    }
    event_keys = {
        "date", "gameDate", "eventDate", "lastGameDate",
        "awayLastGameDate", "homeLastGameDate",
    }
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key not in ignored and key in event_keys and isinstance(item, str):
                    candidate = item[:10]
                    try:
                        datetime.fromisoformat(candidate)
                    except ValueError:
                        pass
                    else:
                        found.add(candidate)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(payload)
    return sorted(found)


def assert_database_as_of(con, cutoff, slate_date):
    """Reject contaminated receipts and audit explicit event dates in SQLite payloads."""
    for table in ("gates", "gate_history", "jobs", "cards", "card_versions",
                  "grades", "patches", "watch_events"):
        count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        if count:
            raise ValueError(f"Replay database is contaminated: {table} contains {count} pre-existing row(s)")
    rows = con.execute(
        "SELECT evidence_id, observed_at, stage, kind, payload FROM evidence"
    ).fetchall()
    future = []
    reconstructed = []
    dated_kinds = {}
    undated_kinds = {}
    for row in rows:
        try:
            observed = timestamp(row["observed_at"])
        except (TypeError, ValueError, AttributeError):
            raise ValueError("Evidence database contains an invalid or timezone-free observation timestamp")
        if observed > cutoff:
            future.append(row["evidence_id"])
        if row["stage"] not in ("OFFICIAL", "PROJECTED", "CONFIRMED"):
            raise ValueError(f"Replay database contains disallowed non-pregame evidence stage: {row['stage']}")
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            raise ValueError(f"Evidence payload is invalid JSON: {row['evidence_id']}")
        for clock_key in ('sourceArticlePublishedAt','sourceArticleModifiedAt'):
            if payload.get(clock_key) and timestamp(payload[clock_key])>cutoff:
                raise ValueError('Evidence source article revision is after replay cutoff: '+row['evidence_id'])
        if payload.get("historicalReconstruction") is True:
            reconstructed.append(row["evidence_id"])
        dates = _event_dates(row["kind"], payload)
        if dates:
            dated_kinds[row["kind"]] = dated_kinds.get(row["kind"], 0) + 1
            invalid = [d for d in dates if d >= slate_date]
            if invalid:
                raise ValueError(
                    f"Evidence contains same-day/future event dates for {row['kind']} "
                    f"{row['evidence_id']}: {invalid[:5]}")
        else:
            undated_kinds[row["kind"]] = undated_kinds.get(row["kind"], 0) + 1
    if future:
        raise ValueError(
            f"Evidence database is contaminated by {len(future)} post-cutoff receipt(s): {future[:10]}")
    return {
        "isolatedEvidenceDatabase": True,
        "preExistingCardsGradesGatesAndPatches": False,
        "collectorObservedAtAtOrBeforeCutoff": not bool(reconstructed),
        "reconstructedHistoricalReceiptCount": len(reconstructed),
        "retrospectiveEvidenceNotOriginalHistoricalCapture": bool(reconstructed),
        "knownHistoricalEventDatesStrictlyBeforeSlate": True,
        "datedEventReceiptCountsByKind": dated_kinds,
        "receiptsWithoutExplicitUnderlyingEventDatesByKind": undated_kinds,
        "providerInternalAsOfTimeIndependentlyVerified": False,
        "status": "PARTIAL_HISTORICAL_RECONSTRUCTION_NOT_ASOF_CAPTURED" if reconstructed else "PARTIAL_PROVIDER_ASOF_NOT_EXPOSED",
        "limitation": "Collector observation time is known; provider publication/as-of time is not exposed for every source payload.",
    }

def _replay_attempt(root, day, default_stage, bundle):
    stage = bundle.get('stage', default_stage)
    if stage not in ('PROJECTED', 'CONFIRMED'):
        raise ValueError('Each replay bundle requires PROJECTED or CONFIRMED stage')
    cutoff = timestamp(bundle['cutoff'])
    inputs = bundle['inputs']
    if not inputs or any(
        not row.get('source') or
        timestamp(row.get('collectorObservedAtEarliest') or row.get('availableAt')) > cutoff
        for row in inputs
    ):
        raise ValueError('Missing source inventory or collector observation after cutoff')
    snapshot = json.loads(verified_bytes(root, bundle['snapshot'], bundle['snapshotSha256']))
    games = snapshot['games']
    if not games:
        raise ValueError('Empty game list is not evidence of an off day')
    for game in games:
        start = game.get('startTimeUTC') or game.get('startUTC')
        state = game.get('gameState') or game.get('state')
        if not start or state not in ('FUT', 'PRE', 'LIVE', 'CRIT', 'OFF', 'FINAL', 'GAME_OVER'):
            raise ValueError('Historical snapshot requires an official start time and recognized game state')
        # A slate can contain an earlier game that was already live at the
        # saved cutoff. Preserve it in the snapshot: execute() excludes that
        # game using the historical clock while continuing later games.
    evidence = verified_bytes(root, bundle['evidenceDb'], bundle['evidenceDbSha256'])
    if bundle['evidenceDb'].endswith('.gz'):
        evidence = gzip.decompress(evidence)
    with tempfile.TemporaryDirectory(prefix='blender-replay-') as temp:
        db = Path(temp) / 'replay.sqlite'
        db.write_bytes(evidence)
        con = open_db(str(db))
        try:
            point_in_time_audit = assert_database_as_of(con, cutoff, day)
            result = execute(con, snapshot, day, stage, now=cutoff)
            return {'date': day, 'status': 'REPLAYED', 'cutoff': bundle['cutoff'],
                    'stage': stage, 'inputInventory': inputs,
                    'snapshotSha256': bundle['snapshotSha256'],
                    'evidenceDbSha256': bundle['evidenceDbSha256'],
                    'masterGateOrder': MASTER, 'overlayGateOrder': OVERLAY,
                    'engineResult': {k: v for k, v in result.items() if k != 'scan'},
                    'gateCertification': certify_gates(con, day, stage, result.get('games')),
                    'firstNonpassingGateAudit': first_gate_audit(con, day, stage),
                    'gateDiagnostics': explain_live_blockers(con, day, stage),
                    'historicalClockAppliedToEngineAndPersistence': True,
                    'databaseObservedAtCutoffVerified': not bool(point_in_time_audit['reconstructedHistoricalReceiptCount']),
                    'databasePointInTimeVerified': False,
                    'pointInTimeAudit': point_in_time_audit}
        finally:
            con.close()


def replay_day(root, day, default_stage, bundle):
    """Preserve the first certified issuance across separate pregame windows."""
    attempts=[bundle,*bundle.get('laterPregameAttempts',[])]
    cutoffs=[timestamp(a['cutoff']) for a in attempts]
    if cutoffs!=sorted(set(cutoffs)):
        raise ValueError('Historical first-issuance windows must be ordered and unique')
    reviews=[]
    for attempt in attempts:
        result=_replay_attempt(root,day,default_stage,attempt)
        certified=(result['gateCertification'].get('selectedCoreOnlyFullyCertified') is True
            and bool(result['engineResult'].get('card')))
        reviews.append({'cutoff':attempt['cutoff'],'stage':attempt.get('stage',default_stage),
            'cardIssued':bool(result['engineResult'].get('card')),
            'selectedCoreCertified':certified,
            'errors':result['engineResult'].get('errors',[])})
        if result['engineResult'].get('card'):
            # Even a failed independent certification cannot authorize a
            # hindsight second first-issuance attempt on the same slate.
            break
    result['pregameLifecycleAttempts']=reviews
    result['firstIssuedCardNeverReplacedByLaterHistoricalResearch']=True
    return result


async def grade_ledger(source, target):
    failures = 0
    with source.open(encoding='utf-8') as frozen, target.open('x', encoding='utf-8') as grades:
        for line in frozen:
            row = json.loads(line)
            receipt = {'date': row['date'], 'selectionStatus': row['status'],
                       'selectionRowSha256': hashlib.sha256(line.encode('utf-8')).hexdigest()}
            try:
                if row['status'] == 'VERIFIED_OFF_DAY':
                    grade = {'status': 'VERIFIED_OFF_DAY'}
                elif row['status'] != 'REPLAYED':
                    grade = {'status': row['status']}
                    failures += 1
                else:
                    card = row['engineResult'].get('card')
                    if not card:
                        grade = {'status': 'NO_CORE'}
                        failures += 1
                    elif row['gateCertification'].get('selectedCoreOnlyFullyCertified') is not True:
                        grade = {'status': 'CORE_NOT_CERTIFIED'}
                        failures += 1
                    else:
                        legs = card['current_legs']
                        if len(legs) not in (2, 3) or len({x['gameId'] for x in legs}) != len(legs):
                            raise ValueError('Invalid G18 card shape')
                        receipt['cardId'] = card['card_id']
                        receipt['fingerprint'] = card['fingerprint']
                        grade = await grade_frozen_legs(legs)
            except Exception as exc:
                grade = {'status': 'GRADE_UNAVAILABLE', 'errorType': type(exc).__name__,
                         'reason': str(exc)}
                failures += 1
            grades.write(json.dumps({**receipt, 'grade': grade}) + '\n')
            grades.flush()
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path, help='Pregame bundle manifest with start, end, stage and slates')
    parser.add_argument('output', type=Path, help='New frozen selection JSONL ledger')
    parser.add_argument('--grades', type=Path, help='New postgame JSONL ledger, written after selection closes')
    args = parser.parse_args()
    if args.grades and (args.grades.exists() or args.grades.resolve() == args.output.resolve()):
        parser.error('--grades must be a fresh path different from the selection ledger')
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    stage = manifest.get('stage')
    start, end = date.fromisoformat(manifest['start']), date.fromisoformat(manifest['end'])
    if (stage not in (None, 'PROJECTED', 'CONFIRMED') or end < start):
        parser.error('Expected a valid date range and optional PROJECTED/CONFIRMED default stage')
    failures = 0
    status_counts = Counter()
    schedule = manifest.get('officialSchedule')
    if isinstance(schedule, dict):
        days = sorted(schedule)
        if any(not (start.isoformat() <= day <= end.isoformat()) for day in days):
            parser.error('Official schedule dates must fall inside the manifest range')
    else:
        scheduled = manifest.get('scheduledSlates')
        if isinstance(scheduled, dict):
            days = sorted(scheduled)
        else:
            days = [(start + timedelta(days=offset)).isoformat()
                    for offset in range((end - start).days + 1)]
    verified_off_days = set(manifest.get('verifiedOffDays', []))
    with args.output.open('x', encoding='utf-8') as out:
        for day in days:
            bundle = manifest['slates'].get(day)
            if bundle is None and day in verified_off_days:
                row = {'date': day, 'status': 'VERIFIED_OFF_DAY',
                       'officialSchedule': (schedule or {}).get(day)}
            elif bundle is None:
                schedule_row = (schedule or {}).get(day)
                scheduled = bool((schedule_row or {}).get('games'))
                status = 'SCHEDULED_SOURCE_BLOCKED' if scheduled else 'SCHEDULE_UNVERIFIED'
                row = {'date': day, 'status': status,
                       'officialSchedule': schedule_row,
                       'reason': ('Scheduled slate has no archived point-in-time pregame bundle'
                                  if scheduled else 'No official schedule/off-day receipt')}
                failures += 1
            else:
                try:
                    row = replay_day(args.manifest.parent, day, stage, bundle)
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    row = {'date': day, 'status': 'REPLAY_ERROR',
                           'errorType': type(exc).__name__, 'reason': str(exc)}
                    status_counts['REPLAY_ERROR'] += 1
                    failures += 1
            status_counts[row['status']] += 1
            out.write(json.dumps(row, default=str) + '\n')
            out.flush()
    if args.grades:
        failures += asyncio.run(grade_ledger(args.output, args.grades))
    print(json.dumps({'dateRange': [start.isoformat(), end.isoformat()],
                      'dateCount': len(days), 'statusCounts': dict(status_counts),
                      'selectionLedger': str(args.output),
                      'gradeLedger': str(args.grades) if args.grades else None,
                      'unresolvedDatesRemainNonzeroExit': bool(failures)},
                     sort_keys=True))
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
