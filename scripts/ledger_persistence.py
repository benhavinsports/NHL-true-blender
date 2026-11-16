"""Lossless, zero-cost GitHub ledger transport for NHL True Blender.

GitHub rejects regular files larger than 100 MB. Store the entire canonical
SQLite ledger as a compressed, versioned repository artifact instead of
committing an ever-growing raw SQLite blob. Never drop or rebuild cards,
evidence, grades, or patches to make the database smaller.
"""
from __future__ import annotations
import gzip
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

RAW = Path("state/true_blender.sqlite")
ARCHIVE = Path("state/true_blender.sqlite.gz")
LIMIT = 95_000_000  # margin below GitHub's single-file 100 MiB limit


def _verify(db: Path):
    with sqlite3.connect(str(db),timeout=60) as con:
        con.execute("PRAGMA busy_timeout = 60000")
        result=con.execute("PRAGMA quick_check").fetchone()
        if not result or result[0]!="ok":
            raise RuntimeError("Authoritative SQLite integrity check failed: "+str(result))
    return True


def restore():
    RAW.parent.mkdir(parents=True,exist_ok=True)
    if not ARCHIVE.exists():
        if RAW.exists():
            _verify(RAW)
            print("Using original authoritative raw ledger for first migration")
        else:
            print("No prior ledger: initial authoritative database will be created")
        return
    temp=RAW.with_name(RAW.name+".restore-tmp")
    try:
        with gzip.open(ARCHIVE,"rb") as compressed,open(temp,"wb") as out:
            shutil.copyfileobj(compressed,out,1024*1024)
        if not temp.is_file() or temp.stat().st_size==0:
            raise RuntimeError("Compressed authoritative ledger is empty")
        _verify(temp)
        os.replace(temp,RAW)
        print(f"Restored authoritative ledger ({RAW.stat().st_size} bytes) from gzip")
    finally:
        temp.unlink(missing_ok=True)
        # SQLite WAL-mode quick_check can create sidecar files for the
        # temporary restore path. They are not part of the canonical ledger.
        for suffix in ("-wal","-shm","-journal"):
            Path(str(temp)+suffix).unlink(missing_ok=True)


def prepare():
    if not RAW.exists():
        print("No raw SQLite ledger to archive")
        return
    # Ensure outstanding WAL pages reach the database before compression.
    with sqlite3.connect(str(RAW),timeout=60) as con:
        con.execute("PRAGMA busy_timeout = 60000")
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    _verify(RAW)
    ARCHIVE.parent.mkdir(parents=True,exist_ok=True)
    temp=ARCHIVE.with_name(ARCHIVE.name+".tmp")
    try:
        with open(RAW,"rb") as src,open(temp,"wb") as dest:
            with gzip.GzipFile(fileobj=dest,mode="wb",filename="",
                               compresslevel=6,mtime=0) as gz:
                shutil.copyfileobj(src,gz,1024*1024)
        if temp.stat().st_size>LIMIT:
            raise RuntimeError(
                "Compressed SQLite exceeds safe GitHub blob limit; "
                "do not discard history or publish an incomplete backup")
        with gzip.open(temp,"rb") as inp:
            if inp.read(16) != b"SQLite format 3" + bytes([0]):
                raise RuntimeError("Compressed ledger header failed verification")
        os.replace(temp,ARCHIVE)
        # With the .gitignore rule this removes the tracked raw database from
        # the next commit but leaves the original raw file on this runner.
        subprocess.run(["git","rm","--cached","-f","--ignore-unmatch",
                        str(RAW)],check=True,stdout=subprocess.DEVNULL)
        print(f"Preserved full SQLite ledger as gzip ({ARCHIVE.stat().st_size} bytes)")
    finally:
        temp.unlink(missing_ok=True)


if __name__=="__main__":
    if len(sys.argv)!=2 or sys.argv[1] not in ("restore","prepare"):
        raise SystemExit("Usage: python scripts/ledger_persistence.py restore|prepare")
    globals()[sys.argv[1]]()
