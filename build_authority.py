#!/usr/bin/env python3
"""Bootstrap a draft location 'authority' from our own (noisy) metadata.

We have no external gazetteer, so we synthesize one from the Locke numbers and
free-text location strings that parse.pl extracts. The Locke number is the spine:

  1. hash every (lockenumber, location) pair from the parsed filenames
  2. for each Locke number, pick the most frequent location string as the
     canonical name, then fold the other strings for that Locke into the bundle:
        a. spelling: normalized edit-distance similarity >= threshold
        b. wordspotting: a distinctive token of the canonical appears in the string
     and report how much merges vs. stays residual
  3. photos with NO Locke number are excluded for now and reported separately
     (they won't appear in the mosaic until we build better keys for them)

Outputs (next to --out, default build/):
    authority.tsv        locke -> canonical, counts, merged variants, residuals
    authority_excluded.txt   filenames with no Locke number (the parked set)
and a human-readable summary to stdout.

Usage:
    ./.venv/bin/python build_authority.py --root ~/image_repos/ggm-images
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from ggm_data import load_records, make_filelist, DEFAULT_LIST, DEFAULT_ROOT

SIM_THRESHOLD = 0.84          # normalized similarity to call two strings the same place
MIN_TOKEN_LEN = 4             # a token must be this long to anchor wordspotting

# generic words that should not drive wordspotting
STOP = {
    "the", "of", "a", "an", "to", "from", "near", "at", "in", "on", "and",
    "temple", "shrine", "area", "courtyard", "house", "old", "new", "near",
    "north", "south", "east", "west", "upper", "lower", "main", "site",
    "god", "goddess", "image", "images", "statue", "view", "trip", "set",
}


def normalize(s: str) -> str:
    """NFKD -> strip accents -> lowercase -> punctuation to space -> collapse."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(norm: str) -> set[str]:
    return {t for t in norm.split() if len(t) >= MIN_TOKEN_LEN and t not in STOP}


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def wordspot(canon_norm: str, other_norm: str) -> bool:
    ct, ot = tokens(canon_norm), tokens(other_norm)
    if not ct or not ot:
        return False
    return bool(ct & ot)          # share at least one distinctive token


def build(records):
    with_locke = [r for r in records if r.lockenumber]
    without_locke = [r for r in records if not r.lockenumber]

    # locke -> Counter of raw (non-empty) location strings
    loc_counts: dict[str, Counter] = defaultdict(Counter)
    total_per_locke: Counter = Counter()
    for r in with_locke:
        total_per_locke[r.lockenumber] += 1
        if r.location:
            loc_counts[r.lockenumber][r.location] += 1

    bundles = []          # one per locke number
    for locke in sorted(total_per_locke):
        counter = loc_counts.get(locke, Counter())
        total = total_per_locke[locke]
        named = sum(counter.values())

        # group distinct raw spellings by normalized form
        norm_groups: dict[str, Counter] = defaultdict(Counter)
        for raw, n in counter.items():
            norm_groups[normalize(raw)] += Counter({raw: n})

        canonical = ""
        canon_norm = ""
        merged_photos = residual_photos = 0
        merged_strings: list[str] = []
        residual_strings: list[str] = []
        method = Counter()

        if norm_groups:
            # primary = normalized group with the most photos; display = top raw in it
            canon_norm = max(norm_groups, key=lambda k: sum(norm_groups[k].values()))
            canonical = norm_groups[canon_norm].most_common(1)[0][0]

            for ng, raws in norm_groups.items():
                pcount = sum(raws.values())
                rawlist = list(raws)
                if ng == canon_norm:
                    merged_photos += pcount
                    method["primary"] += pcount
                    merged_strings += rawlist
                elif similar(ng, canon_norm) >= SIM_THRESHOLD:
                    merged_photos += pcount
                    method["spelling"] += pcount
                    merged_strings += rawlist
                elif wordspot(canon_norm, ng):
                    merged_photos += pcount
                    method["wordspot"] += pcount
                    merged_strings += rawlist
                else:
                    residual_photos += pcount
                    residual_strings += rawlist

        bundles.append(dict(
            locke=locke, canonical=canonical, total=total, named=named,
            unnamed=total - named, merged_photos=merged_photos,
            residual_photos=residual_photos, method=method,
            merged_strings=sorted(set(merged_strings)),
            residual_strings=sorted(set(residual_strings)),
        ))

    return bundles, with_locke, without_locke


def write_authority(bundles, path):
    with open(path, "w") as f:
        f.write("locke\tcanonical\tphotos\tnamed\tmerged_photos\tresidual_photos\t"
                "merged_strings\tresidual_strings\n")
        for b in bundles:
            f.write("\t".join([
                b["locke"], b["canonical"], str(b["total"]), str(b["named"]),
                str(b["merged_photos"]), str(b["residual_photos"]),
                " | ".join(b["merged_strings"]),
                " | ".join(b["residual_strings"]),
            ]) + "\n")


def write_excluded(without_locke, path):
    with open(path, "w") as f:
        for r in without_locke:
            f.write(r.title + "\n")


def report(bundles, with_locke, without_locke, total):
    nb = len(bundles)
    n_locked = len(with_locke)
    n_named = sum(b["named"] for b in bundles)
    merged = sum(b["merged_photos"] for b in bundles)
    residual = sum(b["residual_photos"] for b in bundles)
    method = Counter()
    for b in bundles:
        method.update(b["method"])

    def pct(n, d): return f"{100*n/d:.1f}%" if d else "0%"

    print("=" * 64)
    print("AUTHORITY BOOTSTRAP REPORT")
    print("=" * 64)
    print(f"total photos               : {total}")
    print(f"photos WITH a Locke number : {n_locked}  ({pct(n_locked, total)})")
    print(f"photos WITHOUT (excluded)  : {len(without_locke)}  ({pct(len(without_locke), total)})")
    print(f"distinct Locke numbers     : {nb}   <-- candidate sub-mosaics")
    print()
    print("among locked photos:")
    print(f"  have location text       : {n_named}  ({pct(n_named, n_locked)})")
    print(f"  merged into canonical    : {merged}  ({pct(merged, n_named)} of named)")
    print(f"     by primary/spelling/wordspot: "
          f"{method['primary']}/{method['spelling']}/{method['wordspot']}")
    print(f"  residual (unexplained)   : {residual}  ({pct(residual, n_named)} of named)")
    print()

    # bundles whose canonical name is shared by several Locke numbers
    by_name = defaultdict(list)
    for b in bundles:
        if b["canonical"]:
            by_name[normalize(b["canonical"])].append(b)
    shared = {k: v for k, v in by_name.items() if len(v) > 1}
    print(f"canonical names shared by >1 Locke (label-merge candidates): {len(shared)}")
    for k, v in sorted(shared.items(), key=lambda kv: -sum(b['total'] for b in kv[1]))[:8]:
        lk = ", ".join(f"{b['locke']}={b['canonical']}" for b in v)
        print(f"    {v[0]['canonical']!r}: {lk}")
    print()

    print("top 20 bundles by photo count:")
    for b in sorted(bundles, key=lambda b: -b["total"])[:20]:
        res = f"  RESIDUAL[{b['residual_photos']}]: {', '.join(b['residual_strings'][:3])}" \
              if b["residual_photos"] else ""
        print(f"  {b['locke']:>5}  {b['total']:5d}  {b['canonical'][:32]:32}{res}")
    print()

    print("bundles with the most residual strings (data to inspect):")
    for b in sorted(bundles, key=lambda b: -len(b["residual_strings"]))[:10]:
        if not b["residual_strings"]:
            break
        print(f"  {b['locke']:>5} ({b['canonical'][:24]}): "
              f"{' | '.join(b['residual_strings'][:6])}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=DEFAULT_ROOT, help="image repo to scan")
    ap.add_argument("--filelist", default=DEFAULT_LIST, help="master file list")
    ap.add_argument("--refresh", action="store_true", help="regenerate the file list first")
    ap.add_argument("--out", default="build", help="output dir for authority files")
    args = ap.parse_args()

    if args.refresh or not os.path.exists(args.filelist):
        n = make_filelist(args.root, args.filelist)
        print(f"(regenerated {args.filelist}: {n} files)")
    records = load_records(args.filelist, args.root)
    bundles, with_locke, without_locke = build(records)

    os.makedirs(args.out, exist_ok=True)
    write_authority(bundles, os.path.join(args.out, "authority.tsv"))
    write_excluded(without_locke, os.path.join(args.out, "authority_excluded.txt"))
    report(bundles, with_locke, without_locke, len(records))
    print(f"\nwrote {args.out}/authority.tsv and {args.out}/authority_excluded.txt")


if __name__ == "__main__":
    main()
