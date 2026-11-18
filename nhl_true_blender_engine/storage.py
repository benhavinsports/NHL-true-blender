"""Server-side canonical state. An existing Core can never be erased by a fresh run."""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')


def stamp(now=None):
    \"\"\"Return an ET timestamp from the execution clock, including replay cutoffs.\"\"\"
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Persistence clock must be timezone-aware')
    return value.astimezone(ET).isoformat(timespec='microseconds')


def encode(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def fingerprint(legs):
    # Stage and source status deliberately do not change a card's identity.
    entries = sorted((str(x['gameId']), str(x['playerId'])) for x in legs)
    return hashlib.sha256(encode(entries).encode()).hexdigest()


def open_db(db_path=None):
    path = db_path or os.environ.get('BLENDER_DB', '/tmp/nhl_blender.db')
    con = sqlite3.connect(path, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout = 30000')
    con.execute('PRAGMA journal_mode = WAL')
    con.executescript('''
      CREATE TABLE IF NOT EXISTS evidence (
        evidence_id TEXT PRIMARY KEY, slate_date TEXT NOT NULL, stage TEXT NOT NULL,
        game_id TEXT, player_id TEXT, kind TEXT NOT NULL, source_url TEXT NOT NULL,
        observed_at TEXT NOT NULL, payload TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS ix_evidence_date ON evidence(slate_date, stage, kind);
      CREATE TABLE IF NOT EXISTS gates (
        slate_date TEXT NOT NULL, stage TEXT NOT NULL, game_id TEXT NOT NULL,
        player_id TEXT NOT NULL, gate TEXT NOT NULL, disposition TEXT NOT NULL,
        details TEXT NOT NULL, evaluated_at TEXT NOT NULL,
        PRIMARY KEY (slate_date,stage,game_id,player_id,gate)
      );
      CREATE TABLE IF NOT EXISTS gate_history (
        snapshot_hash TEXT PRIMARY KEY, slate_date TEXT NOT NULL,
        stage TEXT NOT NULL, game_id TEXT NOT NULL, player_id TEXT NOT NULL,
        gate TEXT NOT NULL, disposition TEXT NOT NULL,
        details TEXT NOT NULL, evaluated_at TEXT NOT NULL,
        archived_at TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS ix_gate_history_slate
        ON gate_history(slate_date, stage, game_id, player_id);
      CREATE TABLE IF NOT EXISTS jobs (
        run_id TEXT PRIMARY KEY, slate_date TEXT NOT NULL, mode TEXT NOT NULL,
        started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, details TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS cards (
        slate_date TEXT PRIMARY KEY, card_id TEXT NOT NULL UNIQUE,
        initial_legs TEXT NOT NULL, current_legs TEXT NOT NULL,
        stage TEXT NOT NULL, fingerprint TEXT NOT NULL, revision INTEGER NOT NULL,
        first_issued_at TEXT NOT NULL, updated_at TEXT NOT NULL, grade TEXT
      );
      CREATE TABLE IF NOT EXISTS card_versions (
        version_id TEXT PRIMARY KEY, slate_date TEXT NOT NULL,
        card_id TEXT NOT NULL, revision INTEGER NOT NULL, stage TEXT NOT NULL,
        fingerprint TEXT NOT NULL, legs TEXT NOT NULL, rationale TEXT NOT NULL,
        created_at TEXT NOT NULL, UNIQUE (slate_date,revision)
      );
      CREATE TABLE IF NOT EXISTS patches (
        patch_id TEXT PRIMARY KEY, affected_gates TEXT NOT NULL,
        policy TEXT NOT NULL, implementation TEXT NOT NULL,
        validation TEXT NOT NULL, updated_at TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS watch_events (
        event_id TEXT PRIMARY KEY, slate_date TEXT NOT NULL, game_id TEXT NOT NULL,
        category TEXT NOT NULL, old_json TEXT NOT NULL, new_json TEXT NOT NULL,
        source_url TEXT NOT NULL, observed_at TEXT NOT NULL,
        dependent_gates TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS grades (
        card_id TEXT PRIMARY KEY, slate_date TEXT NOT NULL,
        result TEXT NOT NULL, legs TEXT NOT NULL, official_sources TEXT NOT NULL,
        audited_patch_ids TEXT NOT NULL, graded_at TEXT NOT NULL
      );
    ''')
    return con


@contextmanager
def transaction(con):
    con.execute('BEGIN IMMEDIATE')
    try:
        yield con
    except BaseException:
        con.execute('ROLLBACK')
        raise
    else:
        con.execute('COMMIT')


def to_dict(row, json_cols=()):
    if not row:
        return None
    result = dict(row)
    for k in json_cols:
        if result.get(k) is not None:
            result[k] = json.loads(result[k])
    return result


def get_card(con, slate_date):
    return to_dict(con.execute('SELECT * FROM cards WHERE slate_date=?', (slate_date,)).fetchone(),
                   ('initial_legs', 'current_legs', 'grade'))


def log_job(con, run_id, date, mode, status, details, finished=True, now=None):
    now_stamp = stamp(now)
    with transaction(con):
        row = con.execute('SELECT status FROM jobs WHERE run_id=?', (run_id,)).fetchone()
        if row and row['status'] == 'COMPLETE':
            return False
        con.execute('''INSERT INTO jobs VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET
            finished_at=excluded.finished_at,status=excluded.status,details=excluded.details''',
            (run_id, date, mode, now_stamp, now_stamp if finished else None, status, encode(details)))
    return True


def record_evidence(con, item):
    for k in ('evidence_id','slate_date','stage','kind','source_url','observed_at','payload'):
        if not item.get(k):
            raise ValueError('source evidence missing '+k)
    if not str(item['source_url']).startswith(('https://','http://')):
        raise ValueError('Evidence requires a real source URL')
    with transaction(con):
        existing = con.execute('SELECT payload FROM evidence WHERE evidence_id=?', (item['evidence_id'],)).fetchone()
        if existing:
            if existing['payload'] != encode(item['payload']):
                raise ValueError('Immutable evidence receipt conflicts')
            return False
        con.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?)',
                    (item['evidence_id'],item['slate_date'],item['stage'],item.get('game_id'),
                     item.get('player_id'),item['kind'],item['source_url'],item['observed_at'],encode(item['payload'])))
    return True


def save_gates(con, date, stage, records, now=None):
    """Replace the CURRENT execution matrix; archive prior receipts first.

    The previous UPSERT accumulated player traces from earlier G0 attack
    directions across separate runs on the SAME slate. That could report
    214 candidates against 96 currently eligible skaters. Historical
    results remain immutable in gate_history; only this run's records
    participate in live G0-G18 certification.
    """
    # One precise timestamp identifies all 36 source checks in THIS complete
    # execution cohort. Per-row second-resolution clocks could flip halfway
    # through a skater's gates, making genuine original receipts impossible to
    # recover as one run after a later diagnostic overwrite.
    batch_timestamp=stamp(now)
    with transaction(con):
        previous=con.execute(
            """SELECT slate_date,stage,game_id,player_id,gate,disposition,
                      details,evaluated_at FROM gates
               WHERE slate_date=? AND stage=?""",(date,stage)).fetchall()
        for row in previous:
            payload=[row[k] for k in (
                'slate_date','stage','game_id','player_id',
                'gate','disposition','details')]
            digest=hashlib.sha256(encode(payload).encode('utf-8')).hexdigest()
            con.execute(
                """INSERT OR IGNORE INTO gate_history
                   (snapshot_hash,slate_date,stage,game_id,player_id,
                    gate,disposition,details,evaluated_at,archived_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (digest,*payload,row['evaluated_at'],stamp(now)))
        # Records from the last run are replaced as a set. Gate history is
        # archived rather than silently erased or allowed to count as live.
        con.execute("DELETE FROM gates WHERE slate_date=? AND stage=?",
                    (date,stage))
        for x in records:
            con.execute('''INSERT INTO gates VALUES (?,?,?,?,?,?,?,?)''',
                (date,stage,x['gameId'],str(x.get('playerId','GOALIE_ATTACK')),
                 x['gate'],x['disposition'],encode(x.get('details',{})),
                 batch_timestamp))



def assert_card_structure(legs, games_count):
    target = 2 if games_count == 2 else 3
    if games_count < 2 or len(legs) != target:
        raise ValueError(f'G18 expects {target} legs from {games_count} games')
    ids = [str(x['gameId']) for x in legs]
    if len(set(ids)) != len(ids):
        raise ValueError('G18 duplicate game')
    if len({str(x['playerId']) for x in legs}) != len(legs):
        raise ValueError('G18 duplicate player')
    for leg in legs:
        for k in ('gameId','playerId','player','path','startUTC','sourceIds'):
            if not leg.get(k): raise ValueError('G18 leg missing '+k)
        if leg['path'] not in ('PRIMARY','TRANSFER','WHO'):
            raise ValueError('G18 unsupported derived path')


def game_started(leg, now=None):
    now = now or datetime.now(timezone.utc)
    if leg.get('gameState') in ('LIVE','CRIT','OFF','FINAL','GAME_OVER'):
        return True
    start = datetime.fromisoformat(leg['startUTC'].replace('Z','+00:00'))
    return now >= start


def _validate_replacement(con, existing, new_legs, audit, now):
    required = (
        'baselineFingerprint','triggerEvidenceId','oldValue','newValue',
        'affectedGates','dependentGates','priorSurvivorFailure',
        'g105EveryChallenger','g17Contradictions','newFingerprint'
    )
    for key in required:
        if not audit or not audit.get(key):
            raise ValueError('G18 replacement lacks '+key)
    if existing['fingerprint'] != audit['baselineFingerprint']:
        raise ValueError('Replacement baseline card fingerprint mismatch')
    if fingerprint(new_legs) != audit['newFingerprint']:
        raise ValueError('Replacement new fingerprint mismatch')
    # Reject any started-game mutation before consulting source chronology.
    old_by_game = {x['gameId']:x for x in existing['current_legs']}
    new_by_game = {x['gameId']:x for x in new_legs}
    for game_id, leg in old_by_game.items():
        changed = new_by_game.get(game_id)
        if not changed or changed['playerId'] != leg['playerId']:
            if game_started(leg, now):
                raise ValueError('Frozen game leg cannot be replaced after puck drop')
    for leg in new_legs:
        if game_started(leg, now):
            raise ValueError('Cannot insert a changed Core leg after puck drop')
    receipt = con.execute('SELECT * FROM evidence WHERE evidence_id=?',
                          (audit['triggerEvidenceId'],)).fetchone()
    if not receipt or receipt['slate_date'] != existing['slate_date']:
        raise ValueError('G18 source-backed trigger not stored')
    # A replay of yesterday's evidence is not a gate-changing source update.
    # Anchor the trigger to the ACTIVE revision, not the original issuance:
    # otherwise a later change could be authorized by an older receipt.
    # The explicitly user-retracted November 17 invalid-G18 fingerprint is
    # a separate, one-time correction; it must still satisfy the full original
    # gate evidence, but is not an ordinary pregame source-change event.
    explicit_retraction = audit.get('exceptionScope') == 'NOV17_PREVIOUSLY_RETRACTED_FINGERPRINT_ONLY'
    if explicit_retraction:
        # Do not allow callers to bypass chronology by merely supplying the
        # retraction-exception string. The sole exception is the exact
        # independently archived invalid G18 card on November 17.
        if existing['slate_date'] != '2026-11-17':
            raise ValueError('G18 retraction exception outside authorized slate')
        try:
            archived = con.execute(
                'SELECT original_fingerprint,original_card FROM card_retractions '
                'WHERE slate_date=?', (existing['slate_date'],)).fetchone()
            original = json.loads(archived['original_card']) if archived else None
        except (sqlite3.Error, TypeError, ValueError, KeyError):
            original = None
            archived = None
        if (not archived or not original
                or original.get('fingerprint') != existing['fingerprint']
                or archived['original_fingerprint'] != existing['fingerprint']
                or str(existing['first_issued_at']) <= str(original.get('first_issued_at',''))
                or audit.get('retractedOriginalFirstIssuedAt') != original.get('first_issued_at')):
            raise ValueError('G18 retraction exception lacks matching immutable archive')
    else:
        previous_version = con.execute(
            'SELECT created_at FROM card_versions WHERE slate_date=? AND revision=?',
            (existing['slate_date'], existing['revision'])).fetchone()
        if not previous_version or not previous_version['created_at']:
            raise ValueError('G18 replacement has no saved baseline version timestamp')
        try:
            baseline_time = datetime.fromisoformat(previous_version['created_at'].replace('Z','+00:00'))
            source_time = datetime.fromisoformat(receipt['observed_at'].replace('Z','+00:00'))
            if baseline_time.tzinfo is None or source_time.tzinfo is None:
                raise ValueError('Missing timezone')
        except (TypeError, ValueError, AttributeError):
            raise ValueError('G18 replacement source chronology is not verified')
        if source_time <= baseline_time:
            raise ValueError('G18 replacement trigger predates or matches the locked Core revision')
        if source_time > now:
            raise ValueError('G18 replacement trigger is future-dated')
        audit['baselineVersionCreatedAt'] = previous_version['created_at']
        audit['triggerObservedAt'] = receipt['observed_at']
        audit['triggerNewerThanBaselineVersion'] = True
        if audit.get('reason') == 'VERIFIED_G0_ATTACK_SIDE_REVERSAL':
            material=audit.get('g0MaterialSourceChange') or {}
            if (material.get('reason') not in (
                    'MEASURED_GOALIE_WEAK_ORIGIN_CHANGED',
                    'NEW_CONFIRMED_STARTER_IDENTITY')
                    or material.get('triggerEvidenceId') != audit['triggerEvidenceId']
                    or material.get('baselineVersionCreatedAt') != previous_version['created_at']
                    or material.get('triggerObservedAt') != receipt['observed_at']):
                raise ValueError('G18 G0 reversal lacks a changed post-card goalie source')
    if not audit['priorSurvivorFailure'].get('failedGate'):
        raise ValueError('G18 prior player failure gate missing')
    if not audit['priorSurvivorFailure'].get('sourceIds'):
        raise ValueError('G18 prior player failed without sourced proof')
    if not audit['g105EveryChallenger'].get('comparisonRows'):
        raise ValueError('G18 missing G10.5 direct-route challenger proof')
    if not audit['g17Contradictions'].get('sourceIds'):
        raise ValueError('G18 G17 contradicting evidence not sourced')
    # Proof references must be persisted source receipts, not merely narrative URLs.
    required_source_ids=(audit['priorSurvivorFailure'].get('sourceIds',[])
                      +audit['g17Contradictions'].get('sourceIds',[]))
    if not required_source_ids:
        raise ValueError('G18 replacement requires anchored source receipts')
    for proof_id in required_source_ids:
        valid=con.execute('SELECT 1 FROM evidence WHERE evidence_id=? AND slate_date=?',
                          (proof_id,existing['slate_date'])).fetchone()
        if not valid: raise ValueError('G18 replacement proof source receipt absent: '+proof_id)


def save_card(con, slate_date, stage, legs, games_count, audit=None, now=None):
    """Serialized single-record card writes; stage-only updates keep exact identity."""
    assert_card_structure(legs, games_count)
    new_hash = fingerprint(legs)
    if stage not in ('PROJECTED','MIXED','CONFIRMED'):
        raise ValueError('Unknown card stage')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Card persistence clock must be timezone-aware')
    with transaction(con):
        existing = get_card(con, slate_date)
        if existing:
            if existing['fingerprint'] != new_hash:
                _validate_replacement(con, existing, legs, audit, now)
                rationale = {'type':'GATE_VALIDATED_REPLACEMENT','audit':audit}
            else:
                if any(a['playerId'] != b['playerId'] or a['gameId'] != b['gameId']
                       for a,b in zip(sorted(existing['current_legs'],key=lambda k:k['gameId']),
                                      sorted(legs,key=lambda k:k['gameId']))):
                    raise ValueError('Same fingerprint but different recipients')
                if ['PROJECTED','MIXED','CONFIRMED'].index(stage) < ['PROJECTED','MIXED','CONFIRMED'].index(existing['stage']):
                    raise ValueError('Cannot demote confirmed card')
                # Already identical: idempotent, no new version.
                if existing['stage'] == stage:
                    return existing
                rationale = {'type':'SAME_RECIPIENT_STAGE_ADVANCE','sourceIds':sorted({s for l in legs for s in l['sourceIds']})}
                for leg in existing['current_legs']:
                    if game_started(leg,now) and any(n['gameId']==leg['gameId'] and n!=leg for n in legs):
                        # Keep old record exactly, including source status, for frozen legs.
                        raise ValueError('Post-puck stage change modified frozen leg')
            revision = existing['revision']+1
            card_id = existing['card_id']
            con.execute('UPDATE cards SET current_legs=?,stage=?,fingerprint=?,revision=?,updated_at=? WHERE slate_date=?',
                        (encode(legs),stage,new_hash,revision,stamp(now),slate_date))
        else:
            for leg in legs:
                if game_started(leg, now):
                    raise ValueError('Cannot first-issue a card for an already-started game')
            card_id = 'NHL-'+slate_date+'-CANONICAL'
            revision = 1
            rationale = {'type':'FIRST_ISSUANCE','issuedBeforePuckDrop':True}
            # Retraction timestamps are stored to whole seconds, so a
            # genuine independent reissue in that SAME second must still
            # be distinguishable from the original revoked card. A pair
            # of second-rounded stamp() values can wrongly make issuance
            # look older/equal to the retraction event.
            issued_at=stamp(now)
            con.execute('''INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?)''',
                        (slate_date,card_id,encode(legs),encode(legs),stage,new_hash,revision,issued_at,issued_at,None))
        con.execute('''INSERT INTO card_versions VALUES (?,?,?,?,?,?,?,?,?)''',
                    (f'{card_id}-v{revision}',slate_date,card_id,revision,stage,new_hash,
                     encode(legs),encode(rationale),stamp()))
    return get_card(con,slate_date)


def grade_frozen_card(con, slate_date, goal_counts, sources, all_final):
    """Grade original frozen identities. Never re-pick based on outcomes."""
    if not all_final:
        raise ValueError('Cannot grade until all games on the slate are officially final')
    if not sources or not all(str(s).startswith('https://') for s in sources):
        raise ValueError('Official scoring source URLs required')
    with transaction(con):
        card = get_card(con,slate_date)
        if not card: raise ValueError('No issued Core card to grade')
        previous = con.execute('SELECT * FROM grades WHERE card_id=?',(card['card_id'],)).fetchone()
        if previous:
            return to_dict(previous,('legs','official_sources','audited_patch_ids'))
        scored=[]
        for leg in card['current_legs']:
            key=(str(leg['gameId']),str(leg['playerId']))
            if key not in goal_counts:
                raise ValueError('Official credited player goal total missing '+str(key))
            count=goal_counts[key]
            if not isinstance(count,int) or count<0: raise ValueError('Invalid goal count')
            scored.append({'gameId':key[0],'playerId':key[1],'player':leg['player'],
                           'goals':count,'result':'HIT' if count>0 else 'MISS'})
        hit=sum(1 for row in scored if row['goals']>0)
        result='WIN' if hit==len(scored) else 'LOSS'
        con.execute('INSERT INTO grades VALUES (?,?,?,?,?,?,?)',
                    (card['card_id'],slate_date,result,encode(scored),encode(sources),encode([]),stamp()))
        con.execute('UPDATE cards SET grade=? WHERE slate_date=?',
                    (encode({'hits':hit,'legs':len(scored),'result':result}),slate_date))
        return to_dict(con.execute('SELECT * FROM grades WHERE card_id=?',(card['card_id'],)).fetchone(),
                       ('legs','official_sources','audited_patch_ids'))


def record_watch(con, event, start_utc, now=None):
    if now is None: now=datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Watch clock must be timezone-aware')
    start=datetime.fromisoformat(start_utc.replace('Z','+00:00'))
    if now>=start: raise ValueError('Pregame watch frozen at puck drop')
    if not event.get('source_url','').startswith('https://'):
        raise ValueError('Watch change needs verified source URL')
    with transaction(con):
        if con.execute('SELECT 1 FROM watch_events WHERE event_id=?',(event['event_id'],)).fetchone():
            return False
        con.execute('INSERT INTO watch_events VALUES (?,?,?,?,?,?,?,?,?)',
            (event['event_id'],event['slate_date'],event['game_id'],event['category'],
             encode(event['old']),encode(event['new']),event['source_url'],stamp(now),encode(event['dependent_gates'])))
    return True