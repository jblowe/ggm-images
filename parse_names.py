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

# date prefix:  YYYY [-] Month [DD] -    (whitespace already normalized to singles)
# year may be 2 or 4 digits ("10 - October 24 - ...")
DATE_RE = re.compile(r"^(\d{2,4}) ?-? ?([A-Za-z]+)\.? ?(\d{1,2})? ?-+ ?")
# trailing date fragment to strip from a location ("Kwatu Bāhā, 12 Nov." ->
# "Kwatu Bāhā"); handles "DD Mon" and "Mon DD", abbreviated or full, opt. comma.
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
TRAIL_DATE = re.compile(
    r"\s*,?\s*(?:\d{1,2}\s+" + _MON + r"|" + _MON + r"\s+\d{1,2})\s*$", re.IGNORECASE)
# Locke catalog tokens are all K/P/B + digits (verified: max is 1-3 digits).
# Tolerate a space inside ("K 14"->K14), a letter suffix ("K44e"->K44), and a
# missing following space ("P113Nuga"->P113). Guard against false positives:
#   (?!\d)  the digit run is <=3, so a 4-digit YEAR is never grabbed (P2010)
#   (?!-?\d) the token is not followed by -digits, i.e. a "B09-36" batch code
LOCKE_RE = re.compile(r"\b([KPB]) *(\d{1,3})(?!\d)[a-z]*(?!-?\d)")
TRAIL_NUM = re.compile(r" *(\d+) *$")

_PREFIX_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "location_prefixes.txt")


def _load_connectives(path: str = _PREFIX_FILE) -> tuple[str, ...]:
    """Locative phrases that may sit between the date and the Locke number."""
    out = []
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line.lower())
    except FileNotFoundError:
        pass
    # longest first so the most specific connective wins on endswith()
    return tuple(sorted(set(out), key=len, reverse=True))


CONNECTIVES = _load_connectives()


def parse_stem(stem: str):
    """Return (year, month_day, lockenumber, location, imagenumber) from a stem.

    Whitespace is normalized first (fixes double-spaces around dashes). The Locke
    number is accepted even when preceded by locative text, provided that text
    ends with a known connective (see location_prefixes.txt)."""
    s = re.sub(r"\s+", " ", stem).strip()
    # A leading date is optional: many names put it at the end ("..., 12 Nov.")
    # or omit it. Strip it when present; otherwise search the whole stem.
    md = DATE_RE.match(s)
    if md:
        year, month, day = md.group(1), md.group(2), md.group(3) or ""
        rest = s[md.end():].strip(" -,")
    else:
        year, month, day = "", "", ""
        rest = s

    imgnum = ""
    tn = TRAIL_NUM.search(rest)
    if tn:
        imgnum, rest = tn.group(1), rest[:tn.start()].strip(" -,")

    locke, location = "", rest
    lm = LOCKE_RE.search(rest)
    if lm:
        pre = rest[:lm.start()].strip(" -,").lower()
        if pre == "" or any(pre.endswith(c) for c in CONNECTIVES):
            locke = lm.group(1) + lm.group(2)
            location = rest[lm.end():].strip(" -,")

    # strip a trailing date fragment ("..., 12 Nov") left by date-at-end names
    md_trail = TRAIL_DATE.search(location)
    if md_trail:
        location = location[:md_trail.start()].strip(" -,")
        if not (month or day):
            month_day = md_trail.group(0).strip(" ,")        # keep the date we found
            return year, month_day, locke, location, imgnum

    month_day = f"{month} {day}".strip()
    return year, month_day, locke, location, imgnum


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
    file: str = ""            # resolved absolute path on disk


def parse_path(raw: str) -> Record:
    """Parse one thumbnail path into a Record, mirroring parse.pl."""
    line = raw.replace("\r", "").replace("\n", "")
    full = line  # $x: full path

    basename = re.sub(r"^.*/", "", line)
    filename = basename                      # $filename keeps the extension
    stem = THUMB_RE.sub("", basename)        # strip .thumbnail*.jpg

    rec = Record(filename=filename, title=stem, path=f"/ggm-images{full}")

    year, month_day, locke, location, imgnum = parse_stem(stem)
    rec.year = year
    rec.month_day = month_day
    rec.lockenumber = locke
    rec.location = location
    rec.imagenumber = imgnum

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
                # NB: an NFC-normalization pass renamed many files to
                # "*.thumbnail (nfc).jpg" -- those are the Locke-bearing catalog,
                # so both suffixes must be matched or 13k+ photos vanish.
                if fn.lower().endswith((".thumbnail.jpg", ".thumbnail (nfc).jpg")):
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
UNKNOWN_PREFIX = "Unknown: "


def unknown_key(rec: Record) -> str:
    """Key for a location-less photo: 'Unknown: ' + first 3 filename tokens."""
    toks = rec.title.split()
    return (UNKNOWN_PREFIX + " ".join(toks[:3])) if toks else UNKNOWN


def is_unknown(key: str) -> bool:
    return key == UNKNOWN or key.startswith(UNKNOWN_PREFIX)


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
        key = rec.location if rec.location else unknown_key(rec)
        g = by_key.get(key)
        if g is None:
            g = by_key[key] = Group(key=key)
        g.records.append(rec)
        if rec.lockenumber:
            locke_sets[key].add(rec.lockenumber)

    for key, g in by_key.items():
        lockes = sorted(locke_sets.get(key, ()))
        g.lockenumbers = lockes
        if lockes:
            g.label = f"{key} ({', '.join(lockes)})"
        else:
            g.label = key

    # alphabetical by location key, with all Unknown:* blocks clustered at the end
    groups = sorted(by_key.values(), key=lambda g: (is_unknown(g.key), g.key.lower()))
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
    unknown_groups = [g for g in groups if is_unknown(g.key)]
    unknown_n = sum(g.count for g in unknown_groups)
    real = [g for g in groups if not is_unknown(g.key)]
    counts = sorted(g.count for g in real)

    def pct(n): return f"{100*n/total:.1f}%" if total else "0%"

    print(f"photos parsed         : {total}")
    print(f"distinct locations    : {len(real)}")
    print(f"Unknown blocks        : {len(unknown_groups)}  ({unknown_n} photos, {pct(unknown_n)})")
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
