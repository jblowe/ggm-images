#!/usr/bin/env python3
"""Build and maintain the master list of photo files in the image repo, and load
parsed records from it.

We deliberately drive everything off the LIVE filesystem rather than ggm1a.csv:
the CSV is a stale snapshot of the same Perl parse, and we expect to keep
improving the filename parsing. The master list is a plain text file (one
absolute path per line) that you can eyeball and regenerate at any time.

Two thumbnail naming conventions exist on disk because an NFC pass renamed many
files: "*.thumbnail.jpg" and "*.thumbnail (nfc).jpg". The second set is the
Locke-numbered Bāhā/Bahī catalog, so both must be collected.

Regenerate the list:
    ./.venv/bin/python ggm_data.py --root ~/image_repos/ggm-images --write filelist.txt
Inspect it:
    wc -l filelist.txt ; shuf -n 20 filelist.txt
"""

from __future__ import annotations

import argparse
import os

from parse_names import parse_path, Record

DEFAULT_ROOT = os.path.expanduser("~/image_repos/ggm-images")
DEFAULT_LIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filelist.txt")
THUMB_SUFFIXES = (".thumbnail.jpg", ".thumbnail (nfc).jpg")


def scan(image_root: str) -> list[str]:
    """Return sorted absolute paths of every thumbnail under image_root."""
    out = []
    for dirpath, _dirs, files in os.walk(image_root):
        for fn in files:
            if fn.lower().endswith(THUMB_SUFFIXES):
                out.append(os.path.join(dirpath, fn))
    out.sort()
    return out


def make_filelist(image_root: str, list_path: str) -> int:
    """(Re)generate the master file list. Returns the number of files."""
    paths = scan(os.path.expanduser(image_root))
    with open(list_path, "w") as f:
        f.write("\n".join(paths) + ("\n" if paths else ""))
    return len(paths)


def load_records(list_path: str = DEFAULT_LIST,
                 image_root: str = DEFAULT_ROOT) -> list[Record]:
    """Parse every path in the master list into a Record (fields from the
    filename), with .file set to the absolute path on disk.

    If the list is missing, it is generated from image_root first."""
    if not os.path.exists(list_path):
        make_filelist(image_root, list_path)
    records = []
    root = os.path.expanduser(image_root)
    with open(list_path) as f:
        for line in f:
            full = line.rstrip("\n")
            if not full.strip():
                continue
            # parse fields from a root-relative path (leading slash) so the
            # collection/`top` logic works; keep the absolute path as .file
            rel = "/" + os.path.relpath(full, root) if full.startswith(root) else full
            rec = parse_path(rel)
            rec.file = full
            records.append(rec)
    return records


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=DEFAULT_ROOT, help="image repo to scan")
    ap.add_argument("--write", default=DEFAULT_LIST, help="master list path to write")
    args = ap.parse_args()
    n = make_filelist(args.root, args.write)
    print(f"wrote {n} thumbnail paths to {args.write}")


if __name__ == "__main__":
    main()
