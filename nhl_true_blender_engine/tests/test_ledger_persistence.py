"""Do not lose the authoritative Core, grade, or receipts during ledger migration."""
import sqlite3
import subprocess
from scripts.ledger_persistence import RAW,ARCHIVE,prepare,restore

def test_sqlite_ledger_gzip_roundtrip_preserves_all_rows(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git","init","-q"],check=True)
    subprocess.run(["git","config","user.name","test"],check=True)
    subprocess.run(["git","config","user.email","test@example.org"],check=True)
    RAW.parent.mkdir(parents=True)
    with sqlite3.connect(RAW) as con:
        con.execute("CREATE TABLE cards(card_id TEXT PRIMARY KEY, frozen_legs TEXT)")
        con.execute("CREATE TABLE grades(card_id TEXT PRIMARY KEY, result TEXT)")
        con.execute("INSERT INTO cards VALUES ('ONE-CORE','original-legs')")
        con.execute("INSERT INTO grades VALUES ('ONE-CORE','LOSS')")
    subprocess.run(["git","add",str(RAW)],check=True)
    subprocess.run(["git","commit","-qm","historical ledger"],check=True)
    (tmp_path/".gitignore").write_text("state/true_blender.sqlite" + chr(10))
    prepare()
    assert ARCHIVE.is_file()
    assert b"state/true_blender.sqlite" in subprocess.check_output(
        ["git","diff","--cached","--name-only"]).strip()
    RAW.unlink()
    restore()
    with sqlite3.connect(RAW) as con:
        assert con.execute("SELECT frozen_legs FROM cards").fetchone()[0]=="original-legs"
        assert con.execute("SELECT result FROM grades").fetchone()[0]=="LOSS"
