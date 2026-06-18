#!/usr/bin/env python3
"""Parse Gregory Maskarinec photo-archive thumbnail filenames into fields,
and group them by location for the geographic mosaic.

This is a Python port of solr_stuff/parse.pl. The filename regex is reproduced
faithfully so the field extraction matches the original Perl. On top of the
port we add the grouping/labeling logic the mosaic needs (group by location,
aggregate Locke numbers, build a display label, bucket the rest as "Unknown").

Usage:
    # feed a list of thumbnail paths on stdin (paths relative to the image root,
    # with a leading slash so the first component is the collection, as in parse.pl)
    find . -iname '*.thumbnail.jpg' | sed 's#^\\.##' | python3 parse_names.py --stats

    # or point it at the image root directly
    python3 parse_names.py --root ~/image_repos/ggm-images --stats
    python3 parse_names.py --root ~/image_repos/ggm-images --tsv parsed.tsv --json groups.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict

# Faithful port of the parse.pl extraction regex:
#   /^(\d+) ?\-? ([A-Za-z]+) ?(\d+) ?\- ([A-Z]\d+)?,? ?(.*?) ?(\d+)?$/
#   group 1: year      group 2: month     group 3: day
#   group 4: lockenumber (optional)       group 5: location   group 6: imagenumber (optional)
NAME_RE = re.compile(
    r"^(\d+) ?-? ([A-Za-z]+) ?(\d+) ?- ([A-Z]\d+)?,? ?(.*?) ?(\d+)?$"
)

# .thumbnail<anything>.jpg  ->  stem  (parse.pl: s/.thumbnail(.*).jpg//)
THUMB_RE = re.compile(r"\.thumbnail.*\.jpg$", re.IGNORECASE)

CITY_BY_LOCKE = (("K", "Kathmandu"), ("P", "Patan"), ("B", "Bhaktapur"))


@dataclass
class Record:
    year: str = ""
    month_day: str = ""
    lockenumber: str = ""
    location: str = ""        # primary grouping key; "" means Unknown
    imagenumber: str = ""
    title: str = ""           # the filename stem
    city: str = ""
    filename: str = ""        # basename including extension
    top: str = ""             # collection (first path component, normalized)
    path: str = ""            # /ggm-images/<original path>


def parse_path(raw: str) -> Record:
    """Parse one thumbnail path into a Record, mirroring parse.pl."""
    line = raw.replace("\r", "").replace("\n", "")
    full = line  # $x: full path

    basename = re.sub(r"^.*/", "", line)
    filename = basename                      # $filename keeps the extension
    stem = THUMB_RE.sub("", basename)        # strip .thumbnail*.jpg

    rec = Record(filename=filename, title=stem, path=f"/ggm-images{full}")

    m = NAME_RE.match(stem)
    if m:
        year, month, day, locke, location, imgnum = m.groups()
        rec.year = year or ""
        rec.month_day = f"{month} {day}" if (month or day) else ""
        rec.lockenumber = locke or ""
        rec.location = location or ""
        rec.imagenumber = imgnum or ""

    # collection (top): first path component, with parse.pl's normalizations
    mtop = re.match(r"^/(.*?)/", full)
    if mtop:
        top = mtop.group(1)
        top = top.replace(" of the Kathmandu Valley", "")
        top = re.sub(r",.*$", "", top)
        rec.top = top

    for prefix, city in CITY_BY_LOCKE:
        if prefix in rec.lockenumber:
            rec.city = city
            break

    return rec


def read_paths(args) -> list[str]:
    if args.root:
        root = os.path.expanduser(args.root)
        paths = []
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if fn.lower().endswith(".thumbnail.jpg"):
                    full = os.path.join(dirpath, fn)
                    # make path relative to root, leading slash (parse.pl convention)
                    rel = os.path.relpath(full, root)
                    paths.append("/" + rel)
        paths.sort()
        return paths
    return [ln.rstrip("\n") for ln in sys.stdin if ln.strip()]


# ---------------------------------------------------------------------------
# grouping / labeling
# ---------------------------------------------------------------------------

UNKNOWN = "Unknown"


@dataclass
class Group:
    key: str                          # location string ("" -> Unknown)
    label: str = ""                   # display label, e.g. "Cilanco Bāhā (P174, P199)"
    lockenumbers: list[str] = field(default_factory=list)
    records: list[Record] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.records)


def build_groups(records: list[Record]) -> list[Group]:
    """Group records by location. Empty location -> 'Unknown'. Aggregate the
    distinct Locke numbers seen in the group for the label."""
    by_key: dict[str, Group] = {}
    locke_sets: dict[str, set[str]] = defaultdict(set)

    for rec in records:
        key = rec.location if rec.location else UNKNOWN
        g = by_key.get(key)
        if g is None:
            g = by_key[key] = Group(key=key)
        g.records.append(rec)
        if rec.lockenumber:
            locke_sets[key].add(rec.lockenumber)

    for key, g in by_key.items():
        lockes = sorted(locke_sets.get(key, ()))
        g.lockenumbers = lockes
        display = UNKNOWN if key == UNKNOWN else key
        if lockes:
            g.label = f"{display} ({', '.join(lockes)})"
        else:
            g.label = display

    # alphabetical by location key, but force Unknown to the end
    groups = sorted(by_key.values(), key=lambda g: (g.key == UNKNOWN, g.key.lower()))
    return groups


# ---------------------------------------------------------------------------
# output / reporting
# ---------------------------------------------------------------------------

def write_tsv(records: list[Record], path: str) -> None:
    cols = ["year", "month_day", "lockenumber", "location", "imagenumber",
            "title", "city", "filename", "top", "path"]
    with open(path, "w") as f:
        for r in records:
            d = asdict(r)
            f.write("\t".join(str(d[c]) for c in cols) + "\n")


def write_json(groups: list[Group], path: str) -> None:
    out = [{
        "key": g.key,
        "label": g.label,
        "lockenumbers": g.lockenumbers,
        "count": g.count,
        "files": [r.path for r in g.records],
    } for g in groups]
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


def print_stats(records: list[Record], groups: list[Group]) -> None:
    total = len(records)
    unknown = next((g for g in groups if g.key == UNKNOWN), None)
    unknown_n = unknown.count if unknown else 0
    real = [g for g in groups if g.key != UNKNOWN]
    counts = sorted(g.count for g in real)

    def pct(n): return f"{100*n/total:.1f}%" if total else "0%"

    print(f"photos parsed         : {total}")
    print(f"distinct locations    : {len(real)}  (+ Unknown)")
    print(f"Unknown (no location) : {unknown_n}  ({pct(unknown_n)})")
    if counts:
        med = counts[len(counts)//2]
        print(f"photos/location       : min={counts[0]} median={med} max={counts[-1]}")
        tiny = sum(1 for c in counts if c <= 2)
        print(f"locations with <=2    : {tiny}")
    print()
    print("top 15 locations by photo count:")
    for g in sorted(real, key=lambda g: -g.count)[:15]:
        print(f"  {g.count:5d}  {g.label}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help="image root to walk for *.thumbnail.jpg")
    ap.add_argument("--tsv", help="write per-photo TSV here")
    ap.add_argument("--json", help="write grouped JSON here")
    ap.add_argument("--stats", action="store_true", help="print summary stats")
    args = ap.parse_args()

    paths = read_paths(args)
    records = [parse_path(p) for p in paths]
    groups = build_groups(records)

    if args.tsv:
        write_tsv(records, args.tsv)
    if args.json:
        write_json(groups, args.json)
    if args.stats or not (args.tsv or args.json):
        print_stats(records, groups)


if __name__ == "__main__":
    main()
