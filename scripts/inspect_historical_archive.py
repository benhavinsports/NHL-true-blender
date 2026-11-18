"""Read-only inventory of the canonical SQLite archive for point-in-time replay.

This reports what is actually retained; it does not synthesize missing
pregame snapshots or treat a final gate ledger as a replayable input bundle.
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

DB = Path("state/true_blender.sqlite")

def rows(con, sql):
    return [dict(row) for row in con.execute(sql).fetchall()]

def main():
    if not DB.is_file():
        raise SystemExit("Canonical SQLite ledger is absent; restore state/true_blender.sqlite.gz first")
    uri = DB.resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    try:
        tables = {r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        report = {"database": str(DB), "bytes": DB.stat().st_size,
                  "tables": sorted(tables)}
        for table in ("evidence", "gates", "gate_history", "cards",
                      "card_versions", "jobs", "watch_events", "patches"):
            if table not in tables:
                report[table] = {"present": False}
                continue
            report[table] = {"present": True,
                "totalRows": con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]}
            if table in ("evidence", "gates", "gate_history", "cards",
                         "card_versions", "jobs"):
                cols = {x["name"] for x in con.execute(f'PRAGMA table_info("{table}")')}
                if "slate_date" in cols:
                    group = ["slate_date"]
                    for optional in ("stage", "kind", "gate", "disposition", "mode", "status"):
                        if optional in cols:
                            group.append(optional)
                    sql = (f'SELECT {",".join(group)}, COUNT(*) AS rows '
                           f'FROM "{table}" GROUP BY {",".join(group)} '
                           f'ORDER BY slate_date,{",".join(group[1:])}')
                    report[table]["bySlate"] = rows(con, sql)
        if "evidence" in tables:
            report["evidence"]["timeRange"] = rows(con,
                "SELECT MIN(observed_at) AS firstObservedAt, "
                "MAX(observed_at) AS lastObservedAt FROM evidence")[0]
        print(json.dumps(report, sort_keys=True, indent=2))
    finally:
        con.close()

if __name__ == "__main__":
    main()
