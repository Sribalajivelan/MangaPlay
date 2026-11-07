"""Real end-to-end run against a RUNNING server (not part of the pytest suite: it uses real OCR, real
Claude agents and real audio, so it takes minutes and costs model usage).

  .venv\\Scripts\\python.exe server\\tests\\e2e_real_job.py <images_folder> <how_many_pages> [--keep]

Creates a throwaway manga, uploads the first N pages, watches every stage, checks the finished bundle,
then deletes the manga and verifies nothing is left (unless --keep).
"""
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
folder, n_pages = Path(sys.argv[1]), int(sys.argv[2])
keep = "--keep" in sys.argv
pages = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})[:n_pages]

c = httpx.Client(base_url=BASE, timeout=60)
t0 = time.time()


def log(msg):
    print(f"[{time.time() - t0:6.0f}s] {msg}", flush=True)


m = c.post("/api/manga", json={"title": "E2E throwaway"}).json()
ch = c.post(f"/api/manga/{m['id']}/chapters", json={"title": "e2e"}).json()
log(f"manga {m['id']} chapter {ch['id']} created ({ch['status']})")
for i, p in enumerate(pages, 1):
    r = c.put(f"/api/chapters/{ch['id']}/pages/{i}", content=p.read_bytes(), headers={"content-type": "application/octet-stream"})
    r.raise_for_status()
log(f"uploaded {len(pages)} pages")
fin = c.post("/api/chapters/%d/finalize" % ch["id"]).json()
log("finalize -> %s" % fin["status"])

last = None
deadline = time.time() + 30 * 60
while time.time() < deadline:
    s = c.get(f"/api/chapters/{ch['id']}").json()
    key = (s["status"], s["stage"], s["detail"])
    if key != last:
        log(f"{s['status']:<10} stage={s['stage']} progress={s['progress']:.0%} detail={s['detail']} cost=${s['cost_usd']:.2f}")
        last = key
    if s["status"] in ("ready", "failed", "cancelled"):
        break
    time.sleep(3)

print()
log(f"FINAL status={s['status']} error={s['error']} cost=${s['cost_usd']:.2f}")
for st in s.get("stages", []):
    print(f"   {st['stage']:<8} {st['status']:<7} {st['seconds']}s  ${st['cost_usd']:.2f}  {st['note']}")

ok = s["status"] == "ready"
if ok:
    script = c.get(f"/bundle/{ch['id']}/script.json").json()
    voiced = [b for b in script["beats"] if b["tts_text"]]
    types = {}
    for b in script["beats"]:
        types[b["type"]] = types.get(b["type"], 0) + 1
    print(f"   bundle: {len(script['beats'])} beats {types}; voiced {len(voiced)}; all directed={all(b['source']=='directed' for b in script['beats'])}")
    print(f"   cast: {[(x['id'], x['name']) for x in script['cast'][:6]]}")
    missing = [b["id"] for b in voiced if not (b.get("audio") and b.get("audio_x"))]
    print(f"   voiced lines missing audio: {missing}")
    for f in (voiced[0]["audio"], voiced[0]["audio_x"], script["strip"]["slices"][0]["file"]):
        r = c.get(f"/bundle/{ch['id']}/{f}")
        print(f"   GET {f}: {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes")
        ok &= r.status_code == 200 and len(r.content) > 100
    ok &= not missing and len(voiced) > 0

if not keep:
    d = c.delete(f"/api/manga/{m['id']}")
    after = c.get(f"/api/manga/{m['id']}").status_code
    log(f"delete manga -> {d.status_code}; fetching it afterwards -> {after}")
    ok &= d.status_code == 204 and after == 404
print("\nE2E RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
