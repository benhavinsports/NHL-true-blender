"""The canonical Blender ledger must survive both legacy and multipart transport."""
import gzip
import json
import sqlite3
import subprocess

import pytest
from scripts import ledger_persistence as ledger


def _create_ledger():
    ledger.RAW.parent.mkdir(parents=True)
    with sqlite3.connect(ledger.RAW) as con:
        con.execute("CREATE TABLE cards(card_id TEXT PRIMARY KEY, frozen_legs TEXT)")
        con.execute("CREATE TABLE grades(card_id TEXT PRIMARY KEY, result TEXT)")
        con.execute("INSERT INTO cards VALUES ('ONE-CORE','original-legs')")
        con.execute("INSERT INTO grades VALUES ('ONE-CORE','LOSS')")


def _assert_rows():
    with sqlite3.connect(ledger.RAW) as con:
        assert con.execute("SELECT frozen_legs FROM cards").fetchone()[0] == "original-legs"
        assert con.execute("SELECT result FROM grades").fetchone()[0] == "LOSS"


def test_sqlite_chunked_roundtrip_preserves_all_rows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ledger, "CHUNK_BYTES", 64)
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", "config", "user.name", "test"], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.org"], check=True)
    _create_ledger()
    subprocess.run(["git", "add", str(ledger.RAW)], check=True)
    subprocess.run(["git", "commit", "-qm", "historical ledger"], check=True)
    (tmp_path / ".gitignore").write_text("state/true_blender.sqlite\n")
    ledger.prepare()
    manifest = json.loads(ledger.MANIFEST.read_text())
    assert len(manifest["parts"]) > 1
    assert not ledger.ARCHIVE.exists()
    assert all((ledger.ARCHIVE.parent / item["file"]).is_file()
               for item in manifest["parts"])
    assert b"state/true_blender.sqlite" in subprocess.check_output(
        ["git", "diff", "--cached", "--name-only"]).strip()
    ledger.RAW.unlink()
    ledger.restore()
    _assert_rows()
    # Re-preparing the same state uses deterministic gzip names and no duplicate parts.
    ledger.prepare()
    assert json.loads(ledger.MANIFEST.read_text()) == manifest


def test_corrupt_chunk_fails_closed_without_replacing_existing_ledger(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ledger, "CHUNK_BYTES", 80)
    subprocess.run(["git", "init", "-q"], check=True)
    _create_ledger()
    ledger.prepare()
    chunk = ledger.ARCHIVE.parent / json.loads(ledger.MANIFEST.read_text())["parts"][0]["file"]
    chunk.write_bytes(b"bad archive bytes")
    with pytest.raises(RuntimeError, match="chunk verification failed"):
        ledger.restore()
    _assert_rows()


def test_legacy_gzip_restores_without_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _create_ledger()
    with ledger.RAW.open("rb") as source, gzip.open(ledger.ARCHIVE, "wb") as output:
        output.write(source.read())
    ledger.RAW.unlink()
    ledger.restore()
    _assert_rows()
