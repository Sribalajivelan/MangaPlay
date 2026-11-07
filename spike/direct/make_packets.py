"""Build Director packets: an annotated image crop + the draft beats inside it.

A packet is the unit of work for one Director agent (design section 6: one subagent per unit,
bounded context, failures isolated). Packets are cut BETWEEN beats so no bubble is split, and
padded so the agent sees the art around the speakers.

Run: .venv\\Scripts\\python.exe spike\\direct\\make_packets.py <images_folder> <run_dir>
Writes <run_dir>/packets/pNN.png + pNN.json and <run_dir>/packets/index.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "detect"))
from strip import Strip  # noqa: E402

MAX_H = 2400      # max strip rows per packet, excluding padding
MAX_BEATS = 10
PAD = 250
COLORS = [(0, 0, 255), (255, 0, 0), (0, 150, 0), (200, 0, 200), (0, 140, 255), (160, 160, 0)]  # BGR


def beat_extent(b: dict) -> tuple[int, int, int, int]:
    box = b["bubble_box"] or b["box"]
    return min(box[0], b["box"][0]), min(box[1], b["box"][1]), max(box[2], b["box"][2]), max(box[3], b["box"][3])


def chunk_beats(beats: list[dict]) -> list[list[dict]]:
    chunks, cur = [], []
    for b in beats:
        if cur:
            top = min(beat_extent(x)[1] for x in cur)
            if beat_extent(b)[3] - top > MAX_H or len(cur) >= MAX_BEATS:
                chunks.append(cur)
                cur = []
        cur.append(b)
    if cur:
        chunks.append(cur)
    return chunks


def render(strip: Strip, chunk: list[dict], y0: int, y1: int) -> np.ndarray:
    img = np.ascontiguousarray(strip.crop(y0, y1)[:, :, ::-1])
    for i, b in enumerate(chunk):
        x0, by0, x1, by1 = beat_extent(b)
        col = COLORS[i % len(COLORS)]
        cv2.rectangle(img, (x0, by0 - y0), (x1, by1 - y0), col, 3)
        label = b["id"]
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        lx, ly = max(0, x0), max(th + 6, by0 - y0)
        cv2.rectangle(img, (lx, ly - th - 6), (lx + tw + 8, ly + 2), col, -1)
        cv2.putText(img, label, (lx + 4, ly - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return img


def main(images: Path, run: Path) -> None:
    strip = Strip(images)
    data = json.loads((run / "draft_beats.json").read_text(encoding="utf-8"))
    beats = sorted(data["beats"], key=lambda b: (beat_extent(b)[1], beat_extent(b)[0]))
    out = run / "packets"
    out.mkdir(exist_ok=True)

    index = []
    prev_tail: list[dict] = []
    for n, chunk in enumerate(chunk_beats(beats), 1):
        top = min(beat_extent(b)[1] for b in chunk)
        bot = max(beat_extent(b)[3] for b in chunk)
        y0, y1 = max(0, top - PAD), min(strip.height, bot + PAD)
        pid = f"p{n:02d}"
        cv2.imwrite(str(out / f"{pid}.png"), render(strip, chunk, y0, y1))
        packet = {
            "packet_id": pid,
            "strip_y": [y0, y1],
            "image": f"{pid}.png",
            "previous_context": [{"id": b["id"], "type": b["type"], "text": b["text"]} for b in prev_tail],
            "beats": [{
                "id": b["id"],
                "draft_type": b["type"],
                "detector_class": b["detector_class"],
                "draft_text": b["text"],
                "ocr_text_before_spacing_repair": b["ocr_text"],
                "needs_review": b["needs_review"],
                "box_in_image": [b["box"][0], b["box"][1] - y0, b["box"][2], b["box"][3] - y0],
            } for b in chunk],
        }
        (out / f"{pid}.json").write_text(json.dumps(packet, indent=1, ensure_ascii=False), encoding="utf-8")
        index.append({"packet_id": pid, "strip_y": [y0, y1], "height": y1 - y0, "n_beats": len(chunk),
                      "beat_ids": [b["id"] for b in chunk]})
        prev_tail = chunk[-2:]
    (out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    hs = [i["height"] for i in index]
    print(f"{len(index)} packets; height min/median/max {min(hs)}/{sorted(hs)[len(hs)//2]}/{max(hs)}; "
          f"beats per packet {min(i['n_beats'] for i in index)}-{max(i['n_beats'] for i in index)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
