"""FastAPI NHL True Blender backend.

Run locally: uvicorn nhl_true_blender_engine.server:app --host 0.0.0.0 --port 8080
Requires a persistent server and outbound NHL feed access. Static Wix file hosting
cannot run this process. Read-only endpoints are public; writes require RUNNER_KEY.
"""
from __future__ import annotations
import asyncio
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, Field
from .storage import open_db, get_card, stamp, log_job, to_dict
from .sources import NHLClient, official_slate, official_final_grade, collect_watch, SourceUnavailable
from .enrichment import ingest, attach
from .engine import execute, PATCH_IDS, GATE_PATCHES, MASTER, OVERLAY
from .audit import audit_misses

ET=ZoneInfo('America/New_York')
DB_PATH=os.environ.get('BLENDER_DB','/tmp/nhl_blender.db')
RUNNER_KEY=os.environ.get('RUNNER_KEY','')
ENABLE_SCHEDULER=os.environ.get('BLENDER_ENABLE_SCHEDULER','1')=='1'
TICKS=set()


def connection():
    return open_db(DB_PATH)


def require_runner(x_runner_key: str|None=Header(default=None)):
    if not RUNNER_KEY or not x_runner_key or x_runner_key != RUNNER_KEY:
        raise HTTPException(status_code=403,detail='Server administrator key required')


def setup():
    con=connection()
    for patch_id in PATCH_IDS:
        gates=[k for k,v in GATE_PATCHES.items() if patch_id in v]
        con.execute('''INSERT OR IGNORE INTO patches VALUES (?,?,?,?,?,?)''',
            (patch_id,json.dumps(gates),
             'Preserve original user gate behavior; never use a new weight, name override, or favorite.',
             'Gate-specific source checks and/or card identity validation',
             'Structural tests required; prospective live success not established',stamp()))
    con.close()


async def run_pipeline(mode, date, job_id=None):
    if mode not in ('projected','confirmed','watch','grade'):
        raise ValueError('Unsupported job mode')
    job_id=job_id or f'{mode}:{date}:{datetime.now(ET).strftime("%Y%m%d%H%M")}'
    con=connection()
    try:
        if mode=='grade':
            async with ClientSession() as nhl:
                answer=await official_final_grade(nhl,con,date)
            if answer.get('grade'):answer['missAudits']=audit_misses(con,date)
            log_job(con,job_id,date,mode,'COMPLETE' if answer.get('grade') else 'NO_GRADE',answer)
            return answer
        async with ClientSession() as nhl:
            snapshot=await official_slate(nhl,date,con)
        stage='CONFIRMED' if mode=='confirmed' else 'PROJECTED'
        attach(con,snapshot,date,'WATCH' if mode=='watch' else stage)
        if mode=='watch':
            # The watch does not create cards. It records source-verified pre-puck material changes.
            async with ClientSession() as nhl:
                result=await collect_watch(nhl,con,date,snapshot)
            log_job(con,job_id,date,mode,'COMPLETE',result)
            return result
        result=execute(con,snapshot,date,stage)
        result.pop('scan',None)
        if not result.get('card'):
            result['notice']='No published Core without sourced complete G0–G18 + overlay proof.'
        log_job(con,job_id,date,mode,'COMPLETE' if result.get('card') else 'INPUT_INCOMPLETE',
                {k:v for k,v in result.items() if k!='card'})
        return result
    except (SourceUnavailable,ValueError,RuntimeError) as exc:
        result={'status':'EXECUTION_FAILED','mode':mode,'date':date,'error':str(exc),
                'claimOfCompletedG18':False}
        log_job(con,job_id,date,mode,'FAILED',result)
        return result
    finally:con.close()


class ClientSession:
    async def __aenter__(self):
        self.client=NHLClient();return self.client
    async def __aexit__(self,*args):await self.client.close()


async def scheduler():
    """ET/DST-aware schedule; each occurrence idempotent. Requires an always-on host."""
    while True:
        now=datetime.now(ET)
        stamp_minute=now.strftime('%Y-%m-%dT%H:%M%z')
        work=[]
        if now.hour==8 and now.minute==15:work.append(('projected',now.date().isoformat()))
        if now.hour==15 and now.minute==15:work.append(('confirmed',now.date().isoformat()))
        if 8<=now.hour<=23 and now.minute==38:work.append(('watch',now.date().isoformat()))
        if now.minute==30:
            # Overnight official-final check includes yesterday's slate.
            work.append(('grade',(now.date()-timedelta(days=1)).isoformat()))
            work.append(('grade',now.date().isoformat()))
        for mode,date in work:
            key=f'{stamp_minute}:{mode}:{date}'
            if key in TICKS:continue
            TICKS.add(key)
            try:
                await run_pipeline(mode,date,job_id=key)
            except Exception as exc:
                con=connection()
                try:log_job(con,key,date,mode,'FAILED',{'error':str(exc)})
                finally:con.close()
        if len(TICKS)>10000:TICKS.clear()
        await asyncio.sleep(55)


@asynccontextmanager
async def lifespan(app):
    setup()
    worker=asyncio.create_task(scheduler()) if ENABLE_SCHEDULER else None
    yield
    if worker:
        worker.cancel()
        try:await worker
        except asyncio.CancelledError:pass

app=FastAPI(title='NHL True Blender G18 Backend',version='0.1.0',lifespan=lifespan,
            description='Server-side evidence-based G0–G18 execution and immutable cards.')


class EvidenceRequest(BaseModel):
    evidence_id: str
    slate_date: str
    stage: str
    kind: str
    source_url: str
    observed_at: str
    payload: dict = Field(default_factory=dict)
    game_id: str|None=None
    player_id: str|None=None


@app.get('/api/health')
def health():
    con=connection()
    try:
        job=con.execute('SELECT * FROM jobs ORDER BY started_at DESC LIMIT 1').fetchone()
        return {'service':'NHL True Blender G18','backendProcess':'RUNNING',
                'schedulerEnabled':ENABLE_SCHEDULER,'timezone':'America/New_York',
                'nhlFeedAccess':'NOT_VERIFIED_BY_HEALTH_CHECK',
                'lastJob':to_dict(job,('details',)),'gateSequence':MASTER,'overlaySequence':OVERLAY,
                'patchRegistryCount':con.execute('SELECT COUNT(*) FROM patches').fetchone()[0]}
    finally:con.close()


@app.get('/api/state')
def state(date:str):
    con=connection()
    try:
        card=get_card(con,date)
        gate_count=con.execute('SELECT COUNT(*) FROM gates WHERE slate_date=?',(date,)).fetchone()[0]
        evidence_count=con.execute('SELECT COUNT(*) FROM evidence WHERE slate_date=?',(date,)).fetchone()[0]
        jobs=[to_dict(r,('details',)) for r in con.execute('SELECT * FROM jobs WHERE slate_date=? ORDER BY started_at DESC LIMIT 30',(date,))]
        watch=con.execute('SELECT COUNT(*) FROM watch_events WHERE slate_date=?',(date,)).fetchone()[0]
        return {'slateDate':date,'card':card,'gateRows':gate_count,'evidenceRows':evidence_count,
                'watchEvents':watch,'jobs':jobs,'fullLiveG18Confirmed':bool(card)}
    finally:con.close()


@app.get('/api/cards/{date}')
def card(date:str):
    con=connection()
    try:return {'card':get_card(con,date)}
    finally:con.close()


@app.get('/api/gates/{date}')
def gates(date:str,stage:str='PROJECTED',limit:int=1000):
    if limit<1 or limit>10000:raise HTTPException(400,'limit must be 1..10000')
    con=connection()
    try:
        rows=con.execute('''SELECT * FROM gates WHERE slate_date=? AND stage=?
                         ORDER BY game_id,player_id,gate LIMIT ?''',(date,stage,limit)).fetchall()
        return {'items':[to_dict(row,('details',)) for row in rows],
                'total':con.execute('SELECT COUNT(*) FROM gates WHERE slate_date=? AND stage=?',(date,stage)).fetchone()[0]}
    finally:con.close()


@app.get('/api/patches')
def patches():
    con=connection()
    try:return {'items':[to_dict(r,('affected_gates',)) for r in con.execute('SELECT * FROM patches ORDER BY patch_id')]}
    finally:con.close()


@app.get('/api/watch/{date}')
def watch(date:str):
    con=connection()
    try:return {'items':[to_dict(r,('old_json','new_json','dependent_gates')) for r in
            con.execute('SELECT * FROM watch_events WHERE slate_date=? ORDER BY observed_at DESC',(date,))]}
    finally:con.close()


@app.get('/api/grades/{date}')
def grades(date:str):
    con=connection()
    try:
        row=con.execute('SELECT * FROM grades WHERE slate_date=?',(date,)).fetchone()
        return {'grade':to_dict(row,('legs','official_sources','audited_patch_ids'))}
    finally:con.close()


@app.post('/api/evidence',dependencies=[Depends(require_runner)])
def upload_evidence(record:EvidenceRequest):
    con=connection()
    try:
        changed=ingest(con,record.model_dump())
        return {'inserted':changed,'receiptId':record.evidence_id}
    except ValueError as exc:raise HTTPException(422,str(exc))
    finally:con.close()


@app.post('/api/jobs/{mode}',dependencies=[Depends(require_runner)])
async def jobs(mode:str,date:str):
    try:return await run_pipeline(mode,date)
    except ValueError as exc:raise HTTPException(422,str(exc))