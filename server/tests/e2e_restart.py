"""Real restart test: kill the server HARD in the middle of a job, start it again, and check that

  1. the library and reading state are still there,
  2. the interrupted chapter went back to the queue and finishes by itself,
  3. finished steps were not redone (the paid model steps in particular: cost must not double).

Not part of the pytest suite (real OCR, real agents, minutes, model usage).
  .venv\\Scripts\\python.exe server\\tests\\e2e_restart.py <images_folder> <how_many_pages>
It stops whatever is listening on :8000, runs its own servers, and leaves nothing running.
"""
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
BASE = "http://127.0.0.1:8000"
folder, n_pages = Path(sys.argv[1]), int(sys.argv[2])
pages = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})[:n_pages]
t0 = time.time()
logf = open(ROOT / "library" / "_restart_server.log", "ab")


def log(m):
    print(f"[{time.time() - t0:6.0f}s] {m}", flush=True)


def kill_tree(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def port_owner():
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if ":8000 " in line and "LISTENING" in line:
            return int(line.split()[-1])
    return None


def start_server():
    p = subprocess.Popen([PY, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", "8000"], cwd=ROOT,
                         stdout=logf, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            if httpx.get(BASE + "/api/health", timeout=2).status_code == 200:
                return p
        except httpx.HTTPError:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


owner = port_owner()
if owner:
    log(f"stopping the server already on :8000 (pid {owner})")
    kill_tree(owner)
    time.sleep(2)

ok = True
server = start_server()
log(f"server #1 up (pid {server.pid})")
try:
    c = httpx.Client(base_url=BASE, timeout=60)
    before = c.get("/api/manga").json()
    log(f"library has {len(before['manga'])} manga before the test")

    # reading state on the already-imported chapter 1 (must survive the restart)
    c.put("/api/chapters/1/reading-state", json={"beat_id": "b050", "y": 31337, "rate": 1.25, "pace": 450, "expressive": False})

    m = c.post("/api/manga", json={"title": "Restart test"}).json()
    ch = c.post(f"/api/manga/{m['id']}/chapters", json={}).json()
    for i, p in enumerate(pages, 1):
        c.put(f"/api/chapters/{ch['id']}/pages/{i}", content=p.read_bytes(), headers={"content-type": "application/octet-stream"}).raise_for_status()
    c.post(f"/api/chapters/{ch['id']}/finalize").raise_for_status()
    log(f"chapter {ch['id']} queued; waiting until the model step 'direct' is running")

    seen = None
    deadline = time.time() + 15 * 60
    while time.time() < deadline:
        s = c.get(f"/api/chapters/{ch['id']}").json()
        if s["stage"] != seen:
            seen = s["stage"]
            log(f"stage={seen} cost=${s['cost_usd']:.2f}")
        if s["stage"] == "direct":
            break
        if s["status"] in ("failed", "ready"):
            raise RuntimeError(f"job ended before the kill point: {s['status']}")
        time.sleep(0.5)
    cost_before = c.get(f"/api/chapters/{ch['id']}").json()["cost_usd"]
    done_before = [x["stage"] for x in c.get(f"/api/chapters/{ch['id']}").json()["stages"]]
    log(f"KILLING the server hard mid-job. Steps finished so far: {done_before}; cost so far ${cost_before:.2f}")
    kill_tree(server.pid)
    time.sleep(3)

    server = start_server()
    log(f"server #2 up (pid {server.pid})")
    c = httpx.Client(base_url=BASE, timeout=60)

    after = c.get("/api/manga").json()
    names = [x["title"] for x in after["manga"]]
    log(f"library after restart: {names}")
    ok &= "Restart test" in names and "Copying Skills With Affinity!" in names
    rs = c.get("/api/chapters/1/reading-state").json()
    log(f"reading state after restart: {rs}")
    ok &= bool(rs) and rs["beat_id"] == "b050" and rs["y"] == 31337 and rs["rate"] == 1.25 and rs["expressive"] == 0
    s = c.get(f"/api/chapters/{ch['id']}").json()
    log(f"interrupted chapter right after restart: status={s['status']} detail={s['detail']!r}")
    ok &= s["status"] in ("queued", "processing")

    deadline = time.time() + 15 * 60
    while time.time() < deadline:
        s = c.get(f"/api/chapters/{ch['id']}").json()
        if s["status"] in ("ready", "failed", "cancelled"):
            break
        time.sleep(2)
    log(f"FINAL status={s['status']} error={s['error']} cost=${s['cost_usd']:.2f}")
    for st in s["stages"]:
        print(f"   {st['stage']:<8} {st['status']:<7} {st['seconds']}s  ${st['cost_usd']:.2f}  {st['note']}")
    ok &= s["status"] == "ready"
    skipped = [x["stage"] for x in s["stages"] if x["note"] == "already done"]
    log(f"steps skipped as already done after the restart: {skipped}")
    ok &= all(st in skipped for st in done_before if st != "direct")   # everything finished before the kill was NOT redone
    # the paid cast step must not be paid twice
    cast_rows = [x for x in s["stages"] if x["stage"] == "cast"]
    ok &= sum(x["cost_usd"] for x in cast_rows) <= 0.30
    log(f"cast cost rows: {[x['cost_usd'] for x in cast_rows]}")
    script = c.get(f"/bundle/{ch['id']}/script.json")
    ok &= script.status_code == 200
    d = c.delete(f"/api/manga/{m['id']}")
    ok &= d.status_code == 204
    log(f"cleanup: delete -> {d.status_code}")
finally:
    kill_tree(server.pid)
print("\nRESTART TEST:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
