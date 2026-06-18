#!/usr/bin/env python3
"""Build the geographic photo mosaic and its DeepZoom tiles.

Pipeline:
  1. load parsed records from the master file list, keep those with a Locke
  2. group by Locke number; canonical name = most frequent location string
  3. order photos in each block chronologically
  4. render each Locke as a square-ish sub-mosaic with a "Name (Locke)" label
  5. justified-pack the blocks alphabetically (by name) into a ~16:9 canvas
  6. dzsave the canvas into DeepZoom tiles for OpenSeadragon

Photos without a Locke number are parked (not in the mosaic) for now.

Engine is libvips (pyvips): demand-driven, so the full canvas is never
materialized in RAM -- dzsave pulls tiles through the join pipeline.

Examples:
    # fast smoke test: only Lockes with >=40 photos, small cells
    ./.venv/bin/python build_mosaic.py --out build/test --min-photos 40 --cell 96x72
    # full build
    ./.venv/bin/python build_mosaic.py --out build/gm
"""

from __future__ import annotations

import argparse
import math
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pyvips

from parse_names import Record
from ggm_data import load_records, make_filelist, DEFAULT_LIST, DEFAULT_ROOT

WHITE = [255, 255, 255]

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# ordering
# ---------------------------------------------------------------------------

def chrono_key(r: Record):
    """Sort key: year, month, day, image number, then title for stability."""
    try:
        year = int(r.year)
    except ValueError:
        year = 9999
    month = day = 0
    if r.month_day:
        parts = r.month_day.split()
        month = MONTHS.get(parts[0].lower(), 0)
        if len(parts) > 1:
            try:
                day = int(parts[1])
            except ValueError:
                day = 0
    try:
        imgnum = int(r.imagenumber)
    except ValueError:
        imgnum = 0
    return (year, month, day, imgnum, r.title)


# ---------------------------------------------------------------------------
# rendering one block
# ---------------------------------------------------------------------------

def make_cell(path: str, cw: int, ch: int) -> pyvips.Image:
    """Load a thumbnail, fit (no crop) inside cw x ch, pad to exactly cw x ch on white."""
    img = pyvips.Image.thumbnail(path, cw, height=ch, size="down")
    if img.bands == 1:
        img = img.colourspace("srgb")
    if img.hasalpha():
        img = img.flatten(background=WHITE)
    if img.bands == 4:
        img = img[0:3]
    x = (cw - img.width) // 2
    y = (ch - img.height) // 2
    return img.embed(x, y, cw, ch, extend="background", background=WHITE)


def make_label(text: str, width: int, height: int, font: str) -> pyvips.Image:
    """Black sans-serif text on a white band of the given size (3-band sRGB)."""
    pad = max(8, height // 8)
    # Image.text parses Pango markup, so escape &, <, >
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    txt = pyvips.Image.text(
        safe, width=max(1, width - 2 * pad), height=max(1, height - 2 * pad),
        font=font, align="low")                       # 1-band alpha mask, 0..255
    y = max(0, (height - txt.height) // 2)
    alpha = txt.embed(pad, y, width, height, extend="black")  # mask on full band
    gray = (255 - alpha).cast("uchar")                 # white bg, black text
    return gray.bandjoin([gray, gray]).copy(interpretation="srgb")


@dataclass
class Block:
    label: str                       # "Canonical Name (Locke)"
    sortkey: str                     # canonical name, lowercased, for alpha order
    records: list = field(default_factory=list)

    @property
    def count(self):
        return len(self.records)


def build_locke_groups(records: list[Record]) -> list[Block]:
    """Group locked photos by Locke number; canonical name = most frequent
    location string; sort blocks alphabetically by canonical name."""
    by_locke: dict[str, list] = defaultdict(list)
    for r in records:
        if r.lockenumber:
            by_locke[r.lockenumber].append(r)

    blocks = []
    for locke, recs in by_locke.items():
        names = Counter(r.location for r in recs if r.location)
        canonical = names.most_common(1)[0][0] if names else locke
        blocks.append(Block(label=f"{canonical} ({locke})",
                            sortkey=canonical.lower(), records=recs))
    blocks.sort(key=lambda b: (b.sortkey, b.label))
    return blocks


def make_block(block: Block, cw: int, ch: int, gap: int,
               label_h: int, font: str) -> pyvips.Image:
    """Render one Locke's sub-mosaic: square-ish grid of cells + label on top."""
    recs = sorted(block.records, key=chrono_key)
    n = len(recs)
    # square-ish in PIXELS: account for cell aspect ratio
    cols = max(1, round(math.sqrt(n * ch / cw)))
    rows = math.ceil(n / cols)

    cells = [make_cell(r.file, cw, ch) for r in recs]
    # pad last row to a full rectangle so arrayjoin is clean
    while len(cells) < cols * rows:
        cells.append((pyvips.Image.black(cw, ch) + WHITE).copy(interpretation="srgb").cast("uchar"))

    grid = pyvips.Image.arrayjoin(cells, across=cols, shim=gap,
                                  background=WHITE, halign="centre", valign="centre")
    block_w = grid.width
    label = make_label(block.label, block_w, label_h, font)
    return pyvips.Image.arrayjoin([label, grid], across=1, background=WHITE)


# ---------------------------------------------------------------------------
# shelf packing
# ---------------------------------------------------------------------------

def pack_justified(sizes, target_ar, gap, row_h):
    """Justified-rows ('Flickr') layout, preserving the given (alphabetical) order.
    Each row is scaled so its blocks share a common height and fill canvas_w edge
    to edge -- no wasted whitespace. Because rows are filled, total area is
    conserved, so canvas_w = sqrt(total_area * target_ar) lands the aspect ratio.

    Returns (rows, canvas_w, canvas_h) where each row is a list of
    (block_index, scaled_w, scaled_h)."""
    # Justified rows rescale block heights to ~row_h, so area is NOT conserved;
    # the invariant is the sum of aspect ratios. With R rows of height row_h and
    # ~canvas_w/row_h aspect-units per row, AR = canvas_w/(R*row_h) works out to
    # target_ar when canvas_w = row_h * sqrt(total_aspect * target_ar).
    total_aspect = sum(w / h for w, h in sizes)
    canvas_w = max(round(row_h * math.sqrt(total_aspect * target_ar)),
                   max(round((w / h) * row_h) for w, h in sizes))

    def justify(cur, last):
        n = len(cur)
        avail = canvas_w - gap * (n - 1)
        aspect_sum = sum(w / h for _, w, h in cur)
        h = row_h if last else max(1, round(avail / aspect_sum))
        out, x = [], 0
        for j, (i, w, hh) in enumerate(cur):
            bw = max(1, round((w / hh) * h))
            out.append((i, bw, h))
        return out, h

    rows, cur, asum = [], [], 0.0
    for i, (w, h) in enumerate(sizes):
        cur.append((i, w, h))
        asum += w / h
        if row_h * asum + gap * (len(cur) - 1) >= canvas_w:
            rows.append(justify(cur, last=False))
            cur, asum = [], 0.0
    if cur:
        rows.append(justify(cur, last=True))

    laid = [r for r, _h in rows]
    canvas_h = sum(h for _r, h in rows) + gap * (len(rows) - 1)
    return laid, canvas_w, canvas_h


def fit(img: pyvips.Image, w: int, h: int) -> pyvips.Image:
    """Resize img to exactly w x h."""
    out = img.resize(w / img.width, vscale=h / img.height)
    if out.width != w or out.height != h:           # correct rounding drift
        out = out.embed(0, 0, w, h, extend="background", background=WHITE)
    return out


def assemble(blocks: list[pyvips.Image], rows, canvas_w: int, gap: int) -> pyvips.Image:
    """Resize each block to its justified size, hconcat into row strips, vconcat."""
    strips = []
    for row in rows:                                 # row: [(idx, w, h), ...]
        sized = [fit(blocks[i], w, h) for i, w, h in row]
        strip = pyvips.Image.arrayjoin(sized, across=len(sized), shim=gap,
                                       background=WHITE, valign="low")
        if strip.width != canvas_w:
            strip = strip.embed(0, 0, canvas_w, strip.height,
                                extend="background", background=WHITE)
        strips.append(strip)
    return pyvips.Image.arrayjoin(strips, across=1, shim=gap, background=WHITE)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=DEFAULT_ROOT, help="image repo root")
    ap.add_argument("--filelist", default=DEFAULT_LIST, help="master file list")
    ap.add_argument("--refresh", action="store_true", help="regenerate the file list first")
    ap.add_argument("--out", default="build/gm", help="output basename (-> <out>.dzi + <out>_files/)")
    ap.add_argument("--cell", default="160x120", help="cell WxH pixels (no crop, fit+pad)")
    ap.add_argument("--gap", type=int, default=2, help="gap between cells/blocks")
    ap.add_argument("--label-h", type=int, default=80, help="label band height px")
    ap.add_argument("--font", default="sans-serif bold 40", help="pango font for labels")
    ap.add_argument("--aspect", default="16:9", help="target aspect ratio")
    ap.add_argument("--row-height", type=int, default=1600,
                    help="nominal justified row height px (controls #rows, not aspect)")
    ap.add_argument("--min-photos", type=int, default=1, help="skip Lockes with fewer photos (smoke test)")
    ap.add_argument("--tile-size", type=int, default=254)
    ap.add_argument("--overlap", type=int, default=1)
    args = ap.parse_args()

    cw, ch = (int(x) for x in args.cell.lower().split("x"))
    aw, ah = (int(x) for x in args.aspect.split(":"))
    target_ar = aw / ah

    if args.refresh or not os.path.exists(args.filelist):
        n = make_filelist(args.root, args.filelist)
        log(f"regenerated {args.filelist}: {n} files")
    log("loading records ...")
    records = load_records(args.filelist, args.root)
    groups = build_locke_groups(records)
    if args.min_photos > 1:
        groups = [g for g in groups if g.count >= args.min_photos]
    locked = sum(g.count for g in groups)
    log(f"{locked} locked photos in {len(groups)} Locke blocks (cell {cw}x{ch})")

    log("rendering blocks ...")
    blocks, sizes = [], []
    for i, g in enumerate(groups, 1):
        blk = make_block(g, cw, ch, args.gap, args.label_h, args.font)
        blocks.append(blk)
        sizes.append((blk.width, blk.height))
        if i % 100 == 0 or i == len(groups):
            log(f"  block {i}/{len(groups)}  ({g.label[:40]}: {g.count})")

    rows, canvas_w, canvas_h = pack_justified(sizes, target_ar, args.gap, args.row_height)
    log(f"packed into {len(rows)} rows -> canvas {canvas_w} x {canvas_h} "
        f"(AR {canvas_w/canvas_h:.2f}, target {target_ar:.2f})")

    canvas = assemble(blocks, rows, canvas_w, args.gap)
    canvas = canvas.embed(0, 0, canvas_w, canvas_h, extend="background", background=WHITE)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    log(f"dzsave -> {args.out}.dzi  (this streams the whole pipeline; be patient)")
    canvas.dzsave(args.out, suffix=".jpg[Q=85]",
                  tile_size=args.tile_size, overlap=args.overlap)
    log("done.")


if __name__ == "__main__":
    main()
