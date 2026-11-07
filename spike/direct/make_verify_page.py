"""Build a local HTML page for a human to verify Director output beat by beat.

Run: .venv\\Scripts\\python.exe spike\\direct\\make_verify_page.py <run_dir> p05 p13 ...
Writes <run_dir>/verify/index.html + crops. Open it in a browser (file://), mark each beat, press
"Download labels" to save labels.json. Nothing leaves your machine.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import cv2

SPOKEN = {"speech", "thought", "narration", "system", "reaction"}
UP = 220
DOWN = 520


def main(run: Path, pids: list[str]) -> None:
    out = run / "verify"
    out.mkdir(exist_ok=True)
    cast = json.loads((run / "cast" / "cast.json").read_text(encoding="utf-8"))
    names = {c["id"]: (c.get("name") or c.get("role") or c["id"]) for c in cast["characters"]}
    options = [(k, f"{k} - {v}") for k, v in names.items()] + [(k, k) for k in ("narrator", "system", "announcer", "none", "unknown")]

    items = []
    for pid in pids:
        packet = json.loads((run / "packets" / f"{pid}.json").read_text(encoding="utf-8"))
        directed = {b["id"]: b for b in json.loads((run / "directed" / f"{pid}.json").read_text(encoding="utf-8"))["beats"]}
        img = cv2.imread(str(run / "packets" / packet["image"]))
        for pb in packet["beats"]:
            d = directed[pb["id"]]
            if d["type"] in {"credit", "skip", "sfx", "note"} and d["confidence"] >= 0.7:
                continue  # nothing is voiced here and the Director was sure: not worth a human's time
            x0, y0, x1, y1 = pb["box_in_image"]
            # Tails usually point DOWN at the speaker, so show much more below the bubble than above.
            crop = img[max(0, y0 - UP): min(img.shape[0], y1 + DOWN)]
            fn = f"{pb['id']}.jpg"
            cv2.imwrite(str(out / fn), crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
            items.append({"id": pb["id"], "packet": pid, "img": fn, "d": d})

    rows = []
    for it in items:
        d = it["d"]
        sp_opts = "".join(
            f'<option value="{k}"{" selected" if k == d["speaker"] else ""}>{html.escape(label)}</option>' for k, label in options)
        type_opts = "".join(
            f'<option{" selected" if t == d["type"] else ""}>{t}</option>'
            for t in ("speech", "thought", "narration", "system", "reaction", "sfx", "credit", "note", "skip"))
        rows.append(f"""
<section class="beat" data-id="{it['id']}" data-packet="{it['packet']}" data-pred-speaker="{d['speaker']}" data-pred-type="{d['type']}">
  <img src="{it['img']}" loading="lazy">
  <div class="meta">
    <div class="hd"><b>{it['id']}</b> <span class="conf">director confidence {d['confidence']:.2f}</span></div>
    <div class="txt">{html.escape(d['text'])}</div>
    <label>Speaker <select class="sp">{sp_opts}</select></label>
    <label>Type <select class="ty">{type_opts}</select></label>
    <label>Text correct? <select class="tx"><option value="yes">yes</option><option value="no">no</option></select></label>
    <input class="fix" placeholder="correct text (only if text is wrong)">
  </div>
</section>""")

    page = f"""<!doctype html><meta charset="utf-8"><title>Verify directed beats</title>
<style>
 body{{font:15px system-ui,sans-serif;margin:0;background:#f4f4f6;color:#1b1b1f}}
 header{{position:sticky;top:0;background:#fff;border-bottom:1px solid #ccc;padding:10px 16px;z-index:5;display:flex;gap:16px;align-items:center}}
 .beat{{display:flex;gap:16px;margin:12px 16px;padding:10px;background:#fff;border-radius:8px;border:1px solid #ddd}}
 .beat img{{width:380px;max-width:50%;object-fit:contain;border-radius:4px;align-self:flex-start}}
 .meta{{flex:1;display:flex;flex-direction:column;gap:6px}} .txt{{font-weight:600}} .conf{{color:#666;font-size:13px}}
 label{{display:flex;gap:8px;align-items:center}} select,input{{padding:4px;font:inherit}} .fix{{width:100%}}
 @media (prefers-color-scheme:dark){{body{{background:#17171a;color:#eee}} header,.beat{{background:#222;border-color:#444}} .conf{{color:#aaa}}}}
 @media (max-width:700px){{.beat{{flex-direction:column}}.beat img{{width:100%;max-width:100%}}}}
</style>
<header><b>{len(items)} beats</b><span>Fix anything the prediction got wrong, then</span>
<button id="dl">Download labels.json</button><span id="n"></span></header>
{''.join(rows)}
<script>
const $=s=>document.querySelectorAll(s);
$('.beat').forEach(b=>b.querySelectorAll('select,input').forEach(e=>e.addEventListener('change',()=>{{
  const done=[...$('.beat')].filter(x=>x.dataset.touched).length; }})));
document.getElementById('dl').onclick=()=>{{
  const labels=[...$('.beat')].map(b=>({{
    id:b.dataset.id, packet:b.dataset.packet,
    predicted:{{speaker:b.dataset.predSpeaker,type:b.dataset.predType}},
    human:{{speaker:b.querySelector('.sp').value,type:b.querySelector('.ty').value,
            text_correct:b.querySelector('.tx').value==='yes',text_fix:b.querySelector('.fix').value||null}}}}));
  const blob=new Blob([JSON.stringify(labels,null,1)],{{type:'application/json'}});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='labels.json';a.click();
  document.getElementById('n').textContent='saved '+labels.length+' labels';
}};
</script>"""
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"wrote {out / 'index.html'} with {len(items)} beats")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])
