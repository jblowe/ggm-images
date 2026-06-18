#!/usr/bin/env python3
"""Mine candidate locative connectives from the PARKED photos.

A parked (no-Locke) photo whose name still contains a valid Locke token, sitting
behind some text we don't yet recognize, is a candidate: adding the right
trailing phrase to location_prefixes.txt would recover it.

We rank the trailing 1-3 word phrases that precede such tokens, since the
reusable connective is almost always at the tail (".. just south of" -> "south
of"). Output goes to location_prefixes_candidates.txt -- a scratch file you skim;
copy good phrases into the curated location_prefixes.txt. This script NEVER
writes the curated file.
"""

from __future__ import annotations

import os
import re
from collections import Counter

from parse_names import DATE_RE, LOCKE_RE, CONNECTIVES
from ggm_data import load_records

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "location_prefixes_candidates.txt")


def main() -> None:
    recs = load_records()
    parked = [r for r in recs if not r.lockenumber]

    phrases = Counter()      # trailing 1-3 word phrase -> count
    full = Counter()         # whole intervening phrase -> count
    example: dict[str, str] = {}

    for r in parked:
        s = re.sub(r"\s+", " ", r.title).strip()
        md = DATE_RE.match(s)
        rest = s[md.end():].strip(" -,") if md else s
        lm = LOCKE_RE.search(rest)
        if not lm:
            continue
        pre = rest[:lm.start()].strip(" -,").lower()
        if not pre:                       # empty pre would have parsed already
            continue
        if any(pre.endswith(c) for c in CONNECTIVES):
            continue                      # already covered
        full[pre] += 1
        example.setdefault(pre, r.title)
        toks = pre.split()
        for n in (1, 2, 3):
            if len(toks) >= n:
                phrases[" ".join(toks[-n:])] += 1

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# Candidate locative connectives mined from parked photos.\n")
        f.write("# Skim these and copy the good ones into location_prefixes.txt.\n")
        f.write(f"# {sum(full.values())} parked photos have a Locke token behind "
                f"an unrecognized prefix.\n\n")
        f.write("# === trailing phrases (the reusable connective is usually here) ===\n")
        f.write("# count  phrase\n")
        for ph, c in phrases.most_common():
            if c >= 2 and not _looks_like_date(ph):
                f.write(f"{c:5d}  {ph}\n")
        f.write("\n# === full intervening phrases (count >= 2, with an example) ===\n")
        for ph, c in full.most_common():
            if c >= 2 and not _looks_like_date(ph):
                f.write(f"#{c:4d}  {ph!r:40}  e.g. {example[ph][:60]}\n")

    print(f"wrote {OUT}")
    print(f"{sum(full.values())} parked photos with a Locke token behind an "
          f"unrecognized prefix; {sum(1 for _,c in phrases.most_common() if c>=2)} "
          f"trailing-phrase candidates.")
    print("\ntop 25 trailing-phrase candidates:")
    for ph, c in phrases.most_common(60):
        if c >= 2 and not _looks_like_date(ph):
            print(f"  {c:4d}  {ph}")


_MONTHS = ("january february march april may june july august september "
           "october november december").split()


def _looks_like_date(ph: str) -> bool:
    return any(m in ph for m in _MONTHS) or bool(re.fullmatch(r"[\d ]+", ph))


if __name__ == "__main__":
    main()
