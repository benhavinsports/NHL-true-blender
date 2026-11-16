"""Restore/persist the canonical SQLite ledger in lossless gzip form.

GitHub rejects files larger than 100 MiB. The full historical NHL evidence
database exceeds that threshold in raw form even when the engine is correct.
Track a compressed, integrity-checked snapshot using only GitHub's free file
hosting; keep the ordinary SQLite path available during each Actions run.

This is NOT evidence pruning or a substitute Core.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import os
import sqlite3
from pathlib import Path

RAW=Path("state/true_blender.sqlite")
ARCHIVE=Path("state/true_blender.sqlite.gz")
MANIFEST=Path("state/true_blender.manifest.json")
MAX_BLOB_BYTES=95*1024*1024


def checksum(path):
    digest=hashlib.sha256()
    with open(path,"rb") as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def restore():
    if not ARCHIVE.is_file():
        if RAW.is_file():
            print("Canonical raw SQLite ledger available for initial migration")
        else:
            print("No existing ledger; engine will create a new SQLite database")
        return
    manifest=json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    expected=manifest.get("sqliteSha256")
    tmp=RAW.with_name(RAW.name+".restore-tmp")
    try:
        with gzip.open(ARCHIVE,"rb") as inp,open(tmp,"wb") as out:
            for chunk in iter(lambda:inp.read(1024*1024),b""):
                out.write(chunk)
        observed=checksum(tmp)
        if expected and observed!=expected:
            raise ValueError("Canonical compressed SQLite SHA256 mismatch")
        # A lossless restore of the prior one-card state, not an empty DB.
        with sqlite3.connect(tmp) as con:
            result=con.execute("PRAGMA quick_check").fetchone()[0]
        if result!="ok":
            raise ValueError("SQLite integrity check failed after restore: "+str(result))
        RAW.parent.mkdir(parents=True,exist_ok=True)
        os.replace(tmp,RAW)
        print("Restored verified SQLite ledger from compressed GitHub snapshot")
    finally:
        if tmp.exists():tmp.unlink()


def persist():
    if not RAW.is_file():
        raise FileNotFoundError("Canonical SQLite ledger is missing; refusing an empty replacement")
    with sqlite3.connect(RAW) as con:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("VACUUM")
        result=con.execute("PRAGMA quick_check").fetchone()[0]
        if result!="ok":
            raise ValueError("SQLite integrity check failed before archival: "+str(result))
    original=RAW.stat().st_size
    digest=checksum(RAW)
    tmp=ARCHIVE.with_name(ARCHIVE.name+".tmp")
    try:
        with open(RAW,"rb") as inp,gzip.open(tmp,"wb",compresslevel=9) as out:
            for chunk in iter(lambda:inp.read(1024*1024),b""):
                out.write(chunk)
        compressed=tmp.stat().st_size
        if compressed>=MAX_BLOB_BYTES:
            raise ValueError(f"Compressed SQLite exceeds safe GitHub file limit: {compressed}")
        with gzip.open(tmp,"rb") as check:
            verify=hashlib.sha256()
            for chunk in iter(lambda:check.read(1024*1024),b""):
                verify.update(chunk)
        if verify.hexdigest()!=digest:
            raise ValueError("Compressed SQLite failed lossless checksum validation")
        os.replace(tmp,ARCHIVE)
        MANIFEST.write_text(json.dumps({
            "format":"gzip-sqlite-lossless-v1",
            "sqliteSha256":digest,
            "originalBytes":original,
            "compressedBytes":compressed,
            "noEvidencePruned":True,
            "cardStateUntouched":True
        },sort_keys=True,indent=2)+"\n",encoding="utf-8")
        RAW.unlink()
        print(f"Archived SQLite ledger losslessly: {original} -> {compressed} bytes")
    finally:
        if tmp.exists():tmp.unlink()


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("operation",choices=["restore","persist"])
    args=parser.parse_args()
    restore() if args.operation=="restore" else persist()
