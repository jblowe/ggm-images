#!/usr/bin/env python3
"""Report what's in the mosaic: images included/excluded and a per-Locke census.

Writes build/report.md (and prints a summary). Drives off the live file list,
so it always reflects the current parsing.
"""

from __future__ import annotations

import os
from collections import Counter

from ggm_data import load_records, make_filelist, DEFAULT_LIST, DEFAULT_ROOT
from build_mosaic import build_locke_groups, dedup_records

CITY = {"K": "Kathmandu", "P": "Patan", "B": "Bhaktapur"}
OUT = "build/report.md"


def main():
    if not os.path.exists(DEFAULT_LIST):
        make_filelist(DEFAULT_ROOT, DEFAULT_LIST)
    records = load_records(DEFAULT_LIST, DEFAULT_ROOT)
    total = len(records)
    deduped = dedup_records(records)
    n_dedup = len(deduped)
    blocks = build_locke_groups(records)          # dedup + Locke groups + recovery
    included = sum(b.count for b in blocks)
    recovered = sum(1 for _ in open("build/recovered.tsv", encoding="utf-8")) - 1 \
        if os.path.exists("build/recovered.tsv") else 0
    locked = included - recovered
    excluded = n_dedup - included                 # parked, on the deduped basis

    # excluded breakdown: has a location string vs truly bare (deduped, unmatched)
    parked = [r for r in deduped if not r.lockenumber]
    parked_named = sum(1 for r in parked if r.location)
    by_city = Counter(CITY.get(b.records[0].lockenumber[0], "?") for b in blocks)
    city_photos = Counter()
    for b in blocks:
        city_photos[CITY.get(b.records[0].lockenumber[0], "?")] += b.count

    os.makedirs("build", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        w = f.write
        w("# Gregory Maskarinec Photo Archive — mosaic report\n\n")
        w(f"- **Total thumbnails:** {total:,}\n")
        w(f"- **After de-duplication:** {n_dedup:,} (removed {total-n_dedup:,} copies)\n")
        w(f"- **Included in mosaic:** {included:,} in **{len(blocks)} Locke sub-mosaics** "
          f"— {locked:,} Locke-tagged + {recovered:,} recovered via wordspotting\n")
        w(f"- **Excluded (parked):** {excluded:,} — of which {parked_named:,} have a "
          f"location string (candidates for more recovery), {len(parked)-parked_named:,} "
          f"are bare\n\n")

        w("## By city (from Locke prefix)\n\n")
        w("| City | Lockes | Photos |\n|---|--:|--:|\n")
        for c in ("Kathmandu", "Patan", "Bhaktapur", "?"):
            if by_city.get(c):
                w(f"| {c} | {by_city[c]} | {city_photos[c]:,} |\n")
        w("\n")

        w(f"## Locations, by photo count ({len(blocks)} Lockes)\n\n")
        w("| # | Locke | City | Canonical name | Photos |\n|--:|---|---|---|--:|\n")
        for n, b in enumerate(sorted(blocks, key=lambda b: -b.count), 1):
            lk = b.records[0].lockenumber
            name = b.label.rsplit(" (", 1)[0]
            w(f"| {n} | {lk} | {CITY.get(lk[0],'?')} | {name} | {b.count} |\n")

        w(f"\n## Locations, alphabetical\n\n")
        w("| Locke | Canonical name | Photos |\n|---|---|--:|\n")
        for b in blocks:                                    # already alpha-sorted
            w(f"| {b.records[0].lockenumber} | {b.label.rsplit(' (',1)[0]} | {b.count} |\n")

    print(f"wrote {OUT}")
    print(f"total={total:,}  included={included:,} ({100*included/total:.1f}%) in "
          f"{len(blocks)} Lockes  excluded={excluded:,}")
    print("by city:", dict(city_photos))
    print("\ntop 15 by count:")
    for b in sorted(blocks, key=lambda b: -b.count)[:15]:
        print(f"  {b.count:5d}  {b.records[0].lockenumber:5}  {b.label}")
    print("\nsmallest blocks:", sum(1 for b in blocks if b.count == 1), "have 1 photo;",
          sum(1 for b in blocks if b.count <= 3), "have <=3")


if __name__ == "__main__":
    main()
