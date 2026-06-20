# GGM geographic photo mosaic

A zoomable mosaic of the **Gregory Maskarinec photo archive**, with photos grouped
by location (Locke number) into labeled sub-mosaics, justified into a ~16:9 canvas
and served as DeepZoom tiles via [OpenSeadragon](https://openseadragon.github.io/).

Everything is driven off the live thumbnail repo — no database, no committed
tiles. Parsing/grouping is data-driven and tunable through two editable text files.

---

## Setup

Requires **libvips** (the engine) and a non-conda Python (so vips links its own
glib). A virtualenv is used at `.venv`:

```sh
brew install vips
/opt/homebrew/bin/python3.13 -m venv .venv
./.venv/bin/python -m pip install pyvips
```

The image repo is expected at `~/image_repos/ggm-images` (override with `--root`).

---

## Quick start

```sh
# 1. (re)generate the master file list from the live repo
./.venv/bin/python ggm_data.py --root ~/image_repos/ggm-images --write filelist.txt

# 2. build the mosaic -> build/gm.dzi + build/gm_files/
./.venv/bin/python build_mosaic.py --out build/gm

# 3. view it (DeepZoom needs HTTP; file:// will fail with "Unable to load TileSource")
ln -sfn build/gm.dzi gm.dzi && ln -sfn build/gm_files gm_files
python3 -m http.server 8099        # then open http://localhost:8099/
```

---

## Pipeline

```
images ─▶ ggm_data(filelist) ─▶ parse_names(fields) ─▶ build_locke_groups
        (dedup + group + recover) ─▶ build_mosaic(render + dzsave) ─▶ OpenSeadragon
```

| Stage | Module | What it does |
|---|---|---|
| 0. File list | `ggm_data.py` | Walks the repo, writes/maintains `filelist.txt`; `load_records()` parses each path into a `Record`. |
| 1. Parse | `parse_names.py` | Per filename: NFD-normalize → strip leading date → extract **Locke** (`K/P/B`+digits; tolerant of `K 14`, `K44e`, prefixes) → **location**, **image number** → strip trailing date. |
| 2. Group | `build_mosaic.build_locke_groups()` | **Dedup** copies → group by Locke (clean canonical name) → **recover** parked photos by wordspotting against the canonicals. |
| 3. Render | `build_mosaic.py` | Photos justified by native width (no letterbox) + captions; centered labels, borders; blocks justified into 16:9; `vips dzsave` → tiles. |
| 4. View | `index.html` | OpenSeadragon, fits the whole image on open. |

### Locke grouping & recovery

- A photo is **included** if its filename parses a Locke number (`P59 Kwā Bāhā 42`).
- **Dedup** removes duplicate copies of the same photo across collections
  (accent-insensitive filename key, e.g. `Kwā Bāhā 42` == `Kwa Bāhā 42`).
- **Recovery** is a second pass: a parked (no-Locke) photo is assigned to a Locke
  when a canonical name's distinctive-token *signature* is a subset of the photo's
  location tokens — so `near Kwā Bāhā`, `east of Nhū Bāhā`, `Teddy Bears at Māhābu
  Bāhā` all resolve. Generic tokens are suppressed to keep precision.

---

## Tunable inputs (edit, then rerun)

| File | Controls |
|---|---|
| `location_prefixes.txt` | Locative connectives so the parser finds a Locke behind text (`south of`, `torana of`, `at entrance to`). |
| `generic_tokens.txt` | Tokens that must NOT trigger a wordspot recovery match (`hiti`, `kumari`, `hanuman`…) — the precision dial. |

**Curate-and-rerun loop** (no full rebuild needed for tuning):

```sh
# edit generic_tokens.txt / location_prefixes.txt, then:
./.venv/bin/python report.py        # refreshes recovered.tsv, still_parked.txt, report.md in seconds
# when happy with the lists, rebuild the tiles:
./.venv/bin/python build_mosaic.py --out build/gm
```

---

## Scripts

| Script | Purpose |
|---|---|
| `ggm_data.py` | Build/maintain `filelist.txt`; load+parse records. |
| `parse_names.py` | Filename → fields (Locke, location, date, image #). |
| `build_mosaic.py` | Dedup + group + recover + render the DeepZoom mosaic. |
| `report.py` | Census → `report.md`; refreshes `recovered.tsv`, `still_parked.txt`. |
| `build_authority.py` | Bootstrap/validate canonical names (variant-merge stats). Standalone — no dedup/recovery. |
| `mine_prefixes.py` | Mine candidate connectives from parked photos. |
| `deploy.sh` | Publish tiles to a `gh-pages` branch (for builds under the 1 GB Pages limit). |

## Artifacts (in `build/`, git-ignored)

| File | Meaning |
|---|---|
| `gm.dzi` + `gm_files/` | The DeepZoom tile pyramid. |
| `recovered.tsv` | Parked photos pulled into the mosaic by wordspotting (review). |
| `still_parked.txt` | Photos still excluded (`location · filename`) — targets for further recovery tuning. |
| `report.md` | Census: included/excluded, by city, per-Locke counts. |
| `authority.tsv`, `authority_excluded.txt` | Output of `build_authority.py`. |

---

## Key parameters (`build_mosaic.py`)

| Flag | Default | Effect |
|---|---|---|
| `--photo-height` | 720 | Working height per photo (detail vs memory; source maxes ~1030). |
| `--row-height` | 2800 | Justified row height — drives canvas size / pixels-per-photo. |
| `--quality` | 90 | JPEG tile quality. |
| `--no-dedup`, `--no-recover` | (off) | Disable de-duplication / wordspot recovery. |

Detail vs. size: canvas size scales with `--row-height` (not `--photo-height`,
which is free sharpness). Higher detail can exceed the 1 GB GitHub Pages cap → host
the tiles on S3/CloudFront instead.

---

## Notes on the source data

- Thumbnails round-trip to their originals: strip `.thumbnail.jpg` from a thumbnail
  path to get the original's path/stem (the original's extension varies —
  `.jpg`/`.JPG`/`.tif` — so locate it as `stem.*`).
- The repo was once tagged with a literal `" (nfc)"` Unicode marker; that has been
  cleaned up so thumbnail names match the (NFD) originals. Filenames are now
  consistent, and the parser NFD-normalizes anyway for robustness.
