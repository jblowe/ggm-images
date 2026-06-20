#!/usr/bin/env python3
"""Generate the static browse-site manifests from the pipeline.

Emits two JSON files (same shape) consumed by the shared 3-pane app:
  site/locations.json  -- the 290 Locke sub-mosaics (the included photos)
  site/extras.json     -- the parked photos, bundled by parsed location text

Each is {"title": ..., "groups": [{id, title, sub, count, photos:[{src,cap}]}]}.
`src` is the thumbnail path RELATIVE to the image root; the page prepends a
configurable IMG_BASE (a CloudFront URL in production, a local symlink in dev).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict

from ggm_data import load_records
from build_mosaic import build_locke_groups, dedup_records, chrono_key

IMG_ROOT = os.path.expanduser("~/image_repos/ggm-images")
CITY = {"K": "Kathmandu", "P": "Patan", "B": "Bhaktapur"}
SITE = "site"


def rel(path):
    return os.path.relpath(path, IMG_ROOT)


def photos(records):
    return [{"src": rel(r.file), "cap": r.title}
            for r in sorted(records, key=chrono_key)]


def main():
    os.makedirs(SITE, exist_ok=True)
    recs = load_records()
    blocks = build_locke_groups(recs)

    # --- locations.json (included) ---
    groups = []
    for b in blocks:
        lk = b.records[0].lockenumber
        name = b.label.rsplit(" (", 1)[0]
        groups.append({
            "id": lk, "title": name,
            "sub": f"{CITY.get(lk[0], '?')} · {lk}",
            "count": b.count, "photos": photos(b.records),
        })
    # nav order: by city, then location name (so each city heads its block once)
    city_order = {"Kathmandu": 0, "Patan": 1, "Bhaktapur": 2}
    groups.sort(key=lambda g: (city_order.get(g["sub"].split(" · ")[0], 9),
                               g["title"].lower()))
    json.dump({"title": "Maskarinec Photo Archive — by location", "groups": groups},
              open(f"{SITE}/locations.json", "w"), ensure_ascii=False)

    # --- extras.json (parked: deduped, not in any block), bundled by location ---
    in_block = {r.file for b in blocks for r in b.records}
    kept = {r.file for r in dedup_records(recs)}
    parked = [r for r in recs if r.file in kept and r.file not in in_block]

    bundles = defaultdict(list)
    for r in parked:
        bundles[r.location.strip() or "(no location)"].append(r)
    ex, singles = [], []
    for key, rs in sorted(bundles.items(), key=lambda kv: (-len(kv[1]), kv[0].lower())):
        if len(rs) == 1:                    # collapse all one-offs into one bundle
            singles.append(rs[0])
        else:
            ex.append({"id": key, "title": key, "sub": "",
                       "count": len(rs), "photos": photos(rs)})
    if singles:                             # catch-all bundle, listed last
        ex.append({"id": "(singletons)", "title": "Singletons (one-offs)",
                   "sub": "", "count": len(singles), "photos": photos(singles)})
    json.dump({"title": "Maskarinec Extras — unplaced photos", "groups": ex},
              open(f"{SITE}/extras.json", "w"), ensure_ascii=False)

    print(f"locations: {len(groups)} groups, {sum(g['count'] for g in groups)} photos")
    print(f"extras   : {len(ex)} bundles, {sum(g['count'] for g in ex)} photos")
    print(f"wrote {SITE}/locations.json and {SITE}/extras.json")


if __name__ == "__main__":
    main()
