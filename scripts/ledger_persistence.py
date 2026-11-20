"""Lossless, zero-cost GitHub ledger transport for NHL True Blender.

GitHub rejects regular files larger than 100 MB. Store the entire canonical
SQLite ledger as a compressed, versioned repository artifact instead of
committing an ever-growing raw SQLite blob. Never drop or rebuild cards,
evidence, grades, or patches to make the database smaller.
"""
from __future__ import annotations
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

RAW = Path("state/true_blender.sqlite")
ARCHIVE = Path("state/true_blender.sqlite.gz")
LIMIT = 95_000_000  # safe margin below GitHub's 100 MiB blob limit
CHUNK_BYTES = 60_000_000
MANIFEST = Path("state/true_blender.sqlite.chunks.json")


def _verify(db: Path):
    with sqlite3.connect(str(db),timeout=60) as con:
        con.execute("PRAGMA busy_timeout = 60000")
        result=con.execute("PRAGMA quick_check").fetchone()
        if not result or result[0]!="ok":
            raise RuntimeError("Authoritative SQLite integrity check failed: "+str(result))
    return True


def _sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _assemble_chunks(destination: Path):
    """Reassemble the immutable, checked parts before touching the live ledger."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("format") != "sqlite-gzip-chunks-v1":
        raise RuntimeError("Unknown authoritative ledger manifest format")
    entries = manifest.get("parts")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("Authoritative ledger manifest has no archive parts")
    whole = hashlib.sha256()
    total = 0
    with destination.open("wb") as output:
        for index, item in enumerate(entries):
            digest = item.get("sha256", "")
            name = item.get("file")
            if (not isinstance(digest, str) or len(digest) != 64 or
                    name != f"{ARCHIVE.name}.part-{index:04d}-{digest[:16]}"):
                raise RuntimeError("Malformed authoritative ledger chunk identity")
            path = ARCHIVE.parent / name
            if not path.is_file():
                raise RuntimeError(f"Missing authoritative ledger chunk: {name}")
            chunk_hash = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    output.write(block)
                    whole.update(block)
                    chunk_hash.update(block)
                    size += len(block)
            if size != item.get("bytes") or chunk_hash.hexdigest() != digest:
                raise RuntimeError(f"Authoritative ledger chunk verification failed: {name}")
            total += size
    if (total != manifest.get("archiveBytes") or
            whole.hexdigest() != manifest.get("archiveSha256")):
        raise RuntimeError("Authoritative ledger archive checksum mismatch")


def restore():
    RAW.parent.mkdir(parents=True, exist_ok=True)
    if not MANIFEST.exists() and not ARCHIVE.exists():
        if RAW.exists():
            _verify(RAW)
            print("Using original authoritative raw ledger for first migration")
        else:
            print("No prior ledger: initial authoritative database will be created")
        return
    temp = RAW.with_name(RAW.name + ".restore-tmp")
    archive_temp = RAW.with_name(RAW.name + ".archive-restore-tmp")
    try:
        source = ARCHIVE
        if MANIFEST.exists():
            _assemble_chunks(archive_temp)
            source = archive_temp
        with gzip.open(source, "rb") as compressed, temp.open("wb") as output:
            shutil.copyfileobj(compressed, output, 1024 * 1024)
        if not temp.is_file() or temp.stat().st_size == 0:
            raise RuntimeError("Compressed authoritative ledger is empty")
        _verify(temp)
        # Only an entirely verified restore may replace the existing database.
        os.replace(temp, RAW)
        print(f"Restored authoritative ledger ({RAW.stat().st_size} bytes)")
    finally:
        temp.unlink(missing_ok=True)
        archive_temp.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm", "-journal"):
            Path(str(temp) + suffix).unlink(missing_ok=True)


def prepare():
    if not RAW.exists():
        print("No raw SQLite ledger to archive")
        return
    with sqlite3.connect(str(RAW), timeout=60) as con:
        con.execute("PRAGMA busy_timeout = 60000")
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    _verify(RAW)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    temp = ARCHIVE.with_name(ARCHIVE.name + ".tmp")
    try:
        with RAW.open("rb") as src, temp.open("wb") as dest:
            with gzip.GzipFile(fileobj=dest, mode="wb", filename="",
                               compresslevel=6, mtime=0) as gz:
                shutil.copyfileobj(src, gz, 1024 * 1024)
        with gzip.open(temp, "rb") as inp:
            if inp.read(16) != b"SQLite format 3" + bytes([0]):
                raise RuntimeError("Compressed ledger header failed verification")
        entries = []
        archive_hash = hashlib.sha256()
        archive_size = 0
        with temp.open("rb") as compressed:
            for index, block in enumerate(iter(lambda: compressed.read(CHUNK_BYTES), b"")):
                digest = hashlib.sha256(block).hexdigest()
                name = f"{ARCHIVE.name}.part-{index:04d}-{digest[:16]}"
                path = ARCHIVE.parent / name
                if len(block) > LIMIT:
                    raise RuntimeError("Ledger chunk exceeds safe GitHub blob limit")
                if not path.exists() or _sha256(path) != digest:
                    pending = path.with_name(path.name + ".tmp")
                    try:
                        pending.write_bytes(block)
                        if _sha256(pending) != digest:
                            raise RuntimeError("Ledger chunk write verification failed")
                        os.replace(pending, path)
                    finally:
                        pending.unlink(missing_ok=True)
                entries.append({"file": name, "sha256": digest, "bytes": len(block)})
                archive_hash.update(block)
                archive_size += len(block)
        if not entries:
            raise RuntimeError("Empty compressed authoritative ledger")
        manifest = {
            "format": "sqlite-gzip-chunks-v1",
            "archiveSha256": archive_hash.hexdigest(),
            "archiveBytes": archive_size,
            "parts": entries,
        }
        pending_manifest = MANIFEST.with_name(MANIFEST.name + ".tmp")
        try:
            pending_manifest.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n",
                                        encoding="utf-8")
            os.replace(pending_manifest, MANIFEST)
        finally:
            pending_manifest.unlink(missing_ok=True)
        # The manifest now durably references a fully written, verified archive.
        # Retire legacy gzip and obsolete immutable parts only afterwards.
        ARCHIVE.unlink(missing_ok=True)
        retained = {entry["file"] for entry in entries}
        for old in ARCHIVE.parent.glob(ARCHIVE.name + ".part-*"):
            if old.name not in retained:
                old.unlink()
        subprocess.run(["git", "rm", "--cached", "-f", "--ignore-unmatch",
                        str(RAW)], check=True, stdout=subprocess.DEVNULL)
        print(f"Preserved complete SQLite ledger in {len(entries)} checked GitHub-safe chunks "
              f"({archive_size} compressed bytes)")
    finally:
        temp.unlink(missing_ok=True)


if __name__=="__main__":
    if len(sys.argv)!=2 or sys.argv[1] not in ("restore","prepare"):
        raise SystemExit("Usage: python scripts/ledger_persistence.py restore|prepare")
    globals()[sys.argv[1]]()
