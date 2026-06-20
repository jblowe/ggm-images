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
import re
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace

os.environ.setdefault("VIPS_CONCURRENCY", "4")   # fewer tile threads -> lower peak memory
import pyvips

# This is a single huge one-shot pipeline (11k+ images joined); the operation
# cache only bloats memory here, so disable it to keep dzsave from OOMing.
pyvips.cache_set_max(0)
pyvips.cache_set_max_mem(0)

from parse_names import Record
from ggm_data import load_records, make_filelist, DEFAULT_LIST, DEFAULT_ROOT

WHITE = [255, 255, 255]
BORDER_COLOR = [150, 150, 150]      # thin submosaic frame

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

def load_photo(path: str, h: int) -> pyvips.Image:
    """Load a thumbnail scaled to height h, KEEPING its native width (no crop, no
    letterbox padding). This is what kills the white bars around portrait photos."""
    img = pyvips.Image.thumbnail(path, 100000, height=h, size="down")
    if img.bands == 1:
        img = img.colourspace("srgb")
    if img.hasalpha():
        img = img.flatten(background=WHITE)
    if img.bands == 4:
        img = img[0:3]
    return img


def text_strip(text: str, width: int, height: int, font: str,
               bg: int = 255, pad: int | None = None,
               align: str = "left") -> pyvips.Image:
    """Black text on a flat gray-`bg` band (255=white), 3-band sRGB.
    align: 'left' (captions), 'center' (label name), or 'right' (count)."""
    if pad is None:
        pad = max(3, height // 10)
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    txt = pyvips.Image.text(
        safe, width=max(1, width - 2 * pad), height=max(1, height - 2 * pad),
        font=font, align="low")                        # 1-band mask; we place it ourselves
    if align == "center":
        x = max(0, (width - txt.width) // 2)
    elif align == "right":
        x = max(0, width - pad - txt.width)
    else:
        x = pad
    y = max(0, (height - txt.height) // 2)
    alpha = txt.embed(x, y, width, height, extend="black")  # mask on full band
    lvl = ((255 - alpha).cast("float") * (bg / 255.0)).cast("uchar")  # bg, black text
    return lvl.bandjoin([lvl, lvl]).copy(interpretation="srgb")


def make_header(name: str, count: int, width: int, height: int, font: str,
                bg: int) -> pyvips.Image:
    """Header band: name centered; 'NNN photos' right-justified in an opaque box
    inserted over the right edge (so a long name is cleanly clipped by the count,
    never overlapping glyphs)."""
    pad = max(3, height // 10)
    name_full = text_strip(name, width, height, font, bg=bg, align="center")

    # render the count at its natural single-line size (no width/height args, which
    # would wrap or mis-size it)
    txt = pyvips.Image.text(f"{count} photos", font=font)
    boxw = min(txt.width + 2 * pad, max(1, width // 2))
    x = max(0, boxw - pad - txt.width)
    y = max(0, (height - txt.height) // 2)
    alpha = txt.embed(x, y, boxw, height, extend="black")
    lvl = ((255 - alpha).cast("float") * (bg / 255.0)).cast("uchar")  # bg, black text
    box = lvl.bandjoin([lvl, lvl]).copy(interpretation="srgb")
    return name_full.insert(box, width - boxw, 0).copy(interpretation="srgb")


@dataclass
class Block:
    label: str                       # "Canonical Name (Locke)"
    sortkey: str                     # canonical name, lowercased, for alpha order
    records: list = field(default_factory=list)

    @property
    def count(self):
        return len(self.records)


# --- accent-insensitive matching helpers (dedup + wordspot recovery) ---

def _astrip(s: str) -> str:
    """Accent-strip, lowercase, punctuation->space, collapse (for fuzzy match)."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s.lower())).strip()


# structural / directional words that are never a distinctive name token
_BASE_STOP = {
    "the", "of", "a", "an", "to", "from", "at", "in", "on", "and", "near", "by",
    "with", "north", "south", "east", "west", "northeast", "northwest",
    "southeast", "southwest", "upper", "lower", "inner", "outer", "old", "new",
    "main", "baha", "bahi", "bahica", "bahical", "temple", "shrine", "courtyard",
    "entrance", "outside", "inside", "detail", "part", "remains", "toward",
    "towards", "searching", "looking", "possibly", "small", "large", "shrine",
    "side", "front", "behind", "between", "above", "below", "atop",
}

_GENERIC_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "generic_tokens.txt")


def _load_generic(path: str = _GENERIC_FILE) -> set[str]:
    out = set()
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                out.add(line.lower())
    except FileNotFoundError:
        pass
    return out


SIG_STOP = _BASE_STOP | _load_generic()


def _toks(s: str) -> frozenset:
    """Distinctive tokens of a string (len>=3, not a stop/generic word)."""
    return frozenset(t for t in _astrip(s).split()
                     if len(t) >= 3 and t not in SIG_STOP)


def dedup_records(records: list[Record]) -> list[Record]:
    """Drop duplicate copies of the same photo across collections, keyed on the
    accent-insensitive filename stem (so 'Kwā Bāhā 42' == 'Kwa Bāhā 42'). Keeps a
    copy that parsed a Locke over one that didn't."""
    best: dict[str, Record] = {}
    for r in records:
        k = _astrip(r.title)
        cur = best.get(k)
        if cur is None or (r.lockenumber and not cur.lockenumber):
            best[k] = r
    return list(best.values())


def _clean_name(s: str) -> str:
    """Drop a leading number token ('90 Musum Bāhā' -> 'Musum Bāhā')."""
    return re.sub(r"^\d+\s+", "", s).strip(" ,-")


def _name_score(s: str) -> tuple:
    """How place-name-like a location string is (higher is better)."""
    return (
        1 if re.search(r"[^\W\d_]", s) else 0,    # contains a letter
        0 if re.search(r"\d{4}", s) else 1,       # no embedded 4-digit year
        0 if s[:1].isdigit() else 1,              # doesn't start with a digit
    )


def pick_canonical(recs, locke: str) -> str:
    """Canonical name = the most-frequent location string that looks most like a
    place name (letters, no leading digit, no embedded year), with a leading
    number token stripped. Falls back to the Locke if there are no locations."""
    names = Counter(r.location for r in recs if r.location)
    if not names:
        return locke
    best = max(names.items(), key=lambda kv: (_name_score(kv[0]), kv[1]))[0]
    return _clean_name(best) or best


def recover_parked(records, blocks, out="build/recovered.tsv",
                   parked_out="build/still_parked.txt"):
    """Second pass: assign a parked (no-Locke) photo to a Locke when a canonical
    name's distinctive-token signature is a subset of the photo's location tokens
    ('near Kwā Bāhā' -> Kwā Bāhā). Ambiguous ties are skipped. Returns COPIES of
    matched records promoted to their Locke. Writes two review files:
      out         -- what got recovered (locke, canonical, location, filename)
      parked_out  -- what is STILL parked (location, filename) for further tuning."""
    canon = []
    for b in blocks:
        name = b.label.rsplit(" (", 1)[0]
        s = _toks(name)
        if s:
            canon.append((b.records[0].lockenumber, name, s))

    recovered, rows, still = [], [], []
    for r in records:
        if r.lockenumber:                              # already in the mosaic
            continue
        matched = None
        if r.location:
            toks = _toks(r.location)
            if toks:
                cands = sorted(((len(s), lk, nm) for lk, nm, s in canon if s <= toks),
                               reverse=True)
                if cands and not (len(cands) > 1 and cands[0][0] == cands[1][0]
                                  and cands[0][2] != cands[1][2]):
                    matched = cands[0]
        if matched:
            _n, lk, nm = matched
            recovered.append(replace(r, lockenumber=lk))
            rows.append((lk, nm, r.location, r.title))
        else:
            still.append((r.location, r.title))

    if out:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write("locke\tcanonical\tparked_location\tfilename\n")
            for lk, nm, loc, title in sorted(rows):
                f.write(f"{lk}\t{nm}\t{loc}\t{title}\n")
    if parked_out:
        os.makedirs(os.path.dirname(parked_out) or ".", exist_ok=True)
        with open(parked_out, "w", encoding="utf-8") as f:
            f.write("location\tfilename\n")
            for loc, title in sorted(still):           # bare-location rows sort first
                f.write(f"{loc}\t{title}\n")
    return recovered


def build_locke_groups(records: list[Record], dedup=True, recover=True,
                       recovered_out="build/recovered.tsv") -> list[Block]:
    """Dedup copies, group locked photos by Locke (clean canonical name), then
    (optionally) recover parked photos via wordspotting; sort alphabetically."""
    if dedup:
        records = dedup_records(records)

    by_locke: dict[str, list] = defaultdict(list)
    for r in records:
        if r.lockenumber:
            by_locke[r.lockenumber].append(r)

    blocks, by_lk = [], {}
    for locke, recs in by_locke.items():
        canonical = pick_canonical(recs, locke)
        b = Block(label=f"{canonical} ({locke})", sortkey=canonical.lower(), records=recs)
        blocks.append(b)
        by_lk[locke] = b

    if recover:
        for r in recover_parked(records, blocks, recovered_out):
            by_lk[r.lockenumber].records.append(r)

    blocks.sort(key=lambda b: (b.sortkey, b.label))
    return blocks


# ---------------------------------------------------------------------------
# justified packing -- used at BOTH levels (photos->block, blocks->canvas)
# ---------------------------------------------------------------------------

def justified_rows(aspects, row_h, target_ar, gap):
    """Lay items (given width/height aspect ratios, in order) into justified rows:
    items in a row share a height and fill the row width edge-to-edge -- no
    letterbox, no gaps beyond `gap`. The overall width is chosen so the result
    approximates target_ar. Returns (rows, width, height); each row is a list of
    (index, w, h)."""
    if not aspects:
        return [], 1, 1
    total_ar = sum(aspects)
    target_w = max(round(row_h * math.sqrt(total_ar * target_ar)),
                   round(max(aspects) * row_h))

    def close(idxs, last):
        avail = target_w - gap * (len(idxs) - 1)
        s = sum(aspects[i] for i in idxs)
        h = row_h if last else max(1, round(avail / s))
        return [(i, max(1, round(aspects[i] * h)), h) for i in idxs]

    rows, cur, s = [], [], 0.0
    for i, ar in enumerate(aspects):
        cur.append(i)
        s += ar
        if row_h * s + gap * (len(cur) - 1) >= target_w:
            rows.append(close(cur, False))
            cur, s = [], 0.0
    if cur:
        rows.append(close(cur, True))
    width = max(sum(w for _, w, _ in r) + gap * (len(r) - 1) for r in rows)
    height = sum(r[0][2] for r in rows) + gap * (len(rows) - 1)
    return rows, width, height


def fit(img: pyvips.Image, w: int, h: int) -> pyvips.Image:
    out = img.resize(w / img.width, vscale=h / img.height)
    if out.width != w or out.height != h:           # correct rounding drift
        out = out.embed(0, 0, w, h, extend="background", background=WHITE)
    return out


def _cat(imgs, direction, gap):
    """True concatenation of differently-sized images (NOT arrayjoin, which forces
    uniform cells). `shim` inserts the gap; align low = top/left."""
    out = imgs[0]
    for im in imgs[1:]:
        out = out.join(im, direction, shim=gap, expand=True,
                       background=WHITE, align="low")
    return out


def _hjoin(imgs, gap):
    return _cat(imgs, "horizontal", gap)


def _vjoin(imgs, gap):
    return _cat(imgs, "vertical", gap)


def render_rows(images, rows, width, gap) -> pyvips.Image:
    """Resize each image to its (w,h) and assemble the justified rows."""
    strips = [_hjoin([fit(images[i], w, h) for i, w, h in r], gap) for r in rows]
    return _vjoin(strips, gap)


def photo_unit(rec: Record, photo_h: int, cap_h: int, cap_font: str) -> pyvips.Image:
    """A photo with its filename (minus .thumbnail.jpg) as a tiny caption below."""
    img = load_photo(rec.file, photo_h)
    cap = text_strip(rec.title, img.width, cap_h, cap_font, bg=255, pad=2)
    return _vjoin([img, cap], 1)


def make_grid(block: Block, photo_h: int, cap_h: int, cap_font: str,
              gap: int) -> pyvips.Image:
    """One Locke's sub-mosaic: each photo (+caption) at uniform height & native
    width, justified into a square-ish block. No letterbox; `gap` px between photos."""
    recs = sorted(block.records, key=chrono_key)
    units = [photo_unit(r, photo_h, cap_h, cap_font) for r in recs]
    aspects = [u.width / u.height for u in units]
    unit_h = photo_h + 1 + cap_h
    rows, w, _h = justified_rows(aspects, unit_h, target_ar=1.0, gap=gap)
    return render_rows(units, rows, w, gap)


def frame(img, border, margin, border_color):
    """1px (or `border`px) line around img, then a white margin all around."""
    b = img.embed(border, border, img.width + 2 * border, img.height + 2 * border,
                  extend="background", background=border_color)
    return b.embed(margin, margin, b.width + 2 * margin, b.height + 2 * margin,
                   extend="background", background=WHITE)


def assemble_canvas(grids, blocks, rows, label_h, label_font, label_bg,
                    border, margin, border_color) -> pyvips.Image:
    """Each block = constant-size light-gray label over its (scaled) photo grid,
    wrapped in a thin border + margin; blocks justified into rows."""
    out = []
    for r in rows:
        units = []
        for i, w, h in r:
            lab = make_header(blocks[i].label, blocks[i].count, w, label_h,
                              label_font, label_bg)
            grid = fit(grids[i], w, max(1, h - label_h))
            units.append(frame(_vjoin([lab, grid], 0), border, margin, border_color))
        out.append(_hjoin(units, 0))           # margins already space the blocks
    return _vjoin(out, 0)


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
    ap.add_argument("--photo-height", type=int, default=720,
                    help="working height per photo (memory vs detail; source maxes ~1030)")
    ap.add_argument("--photo-gap", type=int, default=4, help="gap between photos (px)")
    ap.add_argument("--caption-h", type=int, default=22, help="per-photo filename caption height px")
    ap.add_argument("--caption-font", default="sans-serif 12", help="pango font for captions")
    ap.add_argument("--label-h", type=int, default=84, help="constant label height px")
    ap.add_argument("--font", default="sans-serif bold 44", help="pango font for labels")
    ap.add_argument("--label-bg", type=int, default=232, help="label background gray (255=white)")
    ap.add_argument("--border", type=int, default=1, help="submosaic border width px")
    ap.add_argument("--margin", type=int, default=3, help="white margin around each submosaic px")
    ap.add_argument("--aspect", default="16:9", help="target aspect ratio")
    ap.add_argument("--row-height", type=int, default=2800,
                    help="nominal justified row height px (controls #rows, not aspect)")
    ap.add_argument("--min-photos", type=int, default=1, help="skip Lockes with fewer photos (smoke test)")
    ap.add_argument("--quality", type=int, default=90, help="JPEG quality for tiles")
    ap.add_argument("--tile-size", type=int, default=254)
    ap.add_argument("--overlap", type=int, default=1)
    args = ap.parse_args()

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
    log(f"{locked} locked photos in {len(groups)} Locke blocks")

    log("rendering blocks (photos justified, native width, captioned) ...")
    grids = []
    for i, g in enumerate(groups, 1):
        grids.append(make_grid(g, args.photo_height, args.caption_h,
                               args.caption_font, args.photo_gap))
        if i % 100 == 0 or i == len(groups):
            log(f"  block {i}/{len(groups)}  ({g.label[:40]}: {g.count})")

    aspects = [gr.width / gr.height for gr in grids]
    block_gap = 2 * (args.border + args.margin)        # account for frame in packing
    rows, canvas_w, _h = justified_rows(aspects, args.row_height, target_ar, block_gap)
    canvas = assemble_canvas(grids, groups, rows, args.label_h, args.font,
                             args.label_bg, args.border, args.margin, BORDER_COLOR)
    log(f"packed into {len(rows)} rows -> canvas {canvas.width} x {canvas.height} "
        f"(AR {canvas.width/canvas.height:.2f}, target {target_ar:.2f})")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    log(f"dzsave -> {args.out}.dzi  (this streams the whole pipeline; be patient)")
    canvas.dzsave(args.out, suffix=f".jpg[Q={args.quality}]",
                  tile_size=args.tile_size, overlap=args.overlap)
    log("done.")


if __name__ == "__main__":
    main()
