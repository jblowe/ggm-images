#!/usr/bin/env python3
"""Write a master TSV joining every thumbnail to its mosaic disposition.

build/master_list.tsv columns:
  path         absolute path under ~/image_repos/ggm-images
  included     yes | no  (is this exact file in the mosaic?)
  status       locke      - included via its own parsed Locke number
               recovered  - included via wordspot recovery
               duplicate  - excluded: a dropped duplicate copy (another copy is in)
               parked     - excluded: no Locke and not recovered
  locke        the Locke number it belongs to ('' if parked/bare)
  submosaic    the sub-mosaic label 'Canonical Name (Locke)' ('' if excluded)
  location     parsed location string
  nfd_differs  yes if the on-disk filename is NOT in NFD form (i.e. NFD parsing
               changed it) -- the "changed by normalization" flag
"""

from __future__ import annotations

import os
import unicodedata

from ggm_data import load_records
from build_mosaic import build_locke_groups, dedup_records

OUT = "build/master_list.tsv"


def nfd_differs(s: str) -> bool:
    return unicodedata.normalize("NFD", s) != s


def main():
    recs = load_records()
    blocks = build_locke_groups(recs)            # dedup + group + recover

    in_block = {}                                # file -> (label, locke)
    for b in blocks:
        lk = b.records[0].lockenumber
        for r in b.records:
            in_block[r.file] = (b.label, lk)
    kept = {r.file for r in dedup_records(recs)}  # the copies that survive dedup

    os.makedirs("build", exist_ok=True)
    counts = {"locke": 0, "recovered": 0, "duplicate": 0, "parked": 0}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("path\tincluded\tstatus\tlocke\tsubmosaic\tlocation\tnfd_differs\n")
        for r in recs:
            if r.file in in_block:
                label, lk = in_block[r.file]
                included, status, submosaic = "yes", \
                    ("locke" if r.lockenumber else "recovered"), label
                locke = lk
            else:
                included, submosaic = "no", ""
                status = "duplicate" if r.file not in kept else "parked"
                locke = r.lockenumber
            counts[status] += 1
            f.write("\t".join([
                r.file, included, status, locke, submosaic, r.location,
                "yes" if nfd_differs(r.title) else "no",
            ]) + "\n")

    print(f"wrote {OUT}  ({len(recs)} rows)")
    for k in ("locke", "recovered", "duplicate", "parked"):
        print(f"  {k:10}: {counts[k]:6d}")
    print(f"  included   : {counts['locke']+counts['recovered']:6d}")
    print(f"  nfd_differs (on-disk name not NFD): "
          f"{sum(1 for r in recs if nfd_differs(r.title))}")


if __name__ == "__main__":
    main()
