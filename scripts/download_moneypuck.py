"""Download public MoneyPuck regular-season aggregate CSVs for current NHL season."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import os
import requests

now=datetime.now(ZoneInfo("America/New_York"))
season=now.year if now.month>=9 else now.year-1
root=f"https://moneypuck.com/moneypuck/playerData/seasonSummary/{season}/regular"
out=Path("data/moneypuck")
out.mkdir(parents=True,exist_ok=True)
for name in ("skaters","goalies","lines","teams"):
    url=f"{root}/{name}.csv"
    response=requests.get(url,timeout=45,headers={"User-Agent":"NHL-True-Blender/1.0"})
    response.raise_for_status()
    if not response.content.startswith((b"playerId,",b"lineId,",b"team,")):
        raise ValueError(f"Unexpected MoneyPuck CSV header: {name} from {url}")
    (out/f"{name}.csv").write_bytes(response.content)
    print(f"{name}: {len(response.content)} bytes from {url}")
with open(os.environ.get("GITHUB_ENV","/tmp/nhl_blender_env"),"a") as f:
    f.write(f"MONEYPUCK_EXPORT_ASOF={now.date().isoformat()}\n")
