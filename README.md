# GGM geographic photo mosaic

A zoomable mosaic of the **Gregory Maskarinec photo archive**, with photos grouped
by location (Locke Number) into labeled sub-mosaics, justified into a ~16:9 canvas
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

| Stage        | Module | What it does |
|--------------|---|---|
| 0._File_list | `ggm_data.py` | Walks the repo, writes/maintains `filelist.txt`; `load_records()` parses each path into a `Record`. |
| 1. Parse     | `parse_names.py` | Per filename: NFD-normalize → strip leading date → extract **Locke** (`K/P/B`+digits; tolerant of `K 14`, `K44e`, prefixes) → **location**, **image number** → strip trailing date. |
| 2. Group     | `build_mosaic.build_locke_groups()` | **Dedup** copies → group by Locke (clean canonical name) → **recover** parked photos by wordspotting against the canonicals. |
| 3. Render    | `build_mosaic.py` | Photos justified by native width (no letterbox) + captions; centered labels, borders; blocks justified into 16:9; `vips dzsave` → tiles. |
| 4. View      | `index.html` | OpenSeadragon, fits the whole image on open. |

### Locke Number grouping & recovery

- A photo is **included** if its filename parses a Locke Number (`P59 Kwā Bāhā 42`).
- **Dedup** removes duplicate copies of the same photo across collections
  (accent-insensitive filename key, e.g. `Kwā Bāhā 42` == `Kwa Bāhā 42`).
- **Recovery** is a second pass: a parked (no-Locke) photo is assigned to a Locke
  when a canonical name's distinctive-token *signature* is a subset of the photo's
  location tokens — so `near Kwā Bāhā`, `east of Nhū Bāhā`, `Teddy Bears at Māhābu
  Bāhā` all resolve. Generic tokens are suppressed to keep precision.

---

## Browse site (static HTML — alternative to the zoom-mosaic)

A lightweight 3-pane browser (header · location nav · masonry stage), generated as
static files. It complements the DeepZoom mosaic: the mosaic is the impressive
overview, this is the practical "pick a place, see its photos" tool. Two pages,
cross-linked:

- `site/index.html` — the **290 Locke sub-mosaics** (the included photos); nav grouped by city, with a filter.
- `site/extras.html` — **"Maskarinec Extras"**: the **24,078 parked** photos, bundled by parsed location text.

Together they cover all **36,313 unique** photos (the deduped set). Photos render as
a CSS-columns masonry with captions and a click-to-zoom lightbox.

Build the manifests (from the same pipeline — `build_locke_groups()`):

```sh
./.venv/bin/python build_site.py        # -> site/locations.json, site/extras.json
```

**Where the images come from** is `IMG_BASE` in `site/app.js`:

```sh
# DEV: symlink the repo so the local server can serve the thumbnails
ln -sfn ~/image_repos/ggm-images site/imgbase
python3 -m http.server 8099
#   http://localhost:8099/site/index.html   (by location)
#   http://localhost:8099/site/extras.html  (Maskarinec Extras)
```

Files: `build_site.py`, `site/{index,extras}.html`, `site/style.css`, `site/app.js`.
Generated / git-ignored: `site/locations.json`, `site/extras.json`, `site/imgbase`.

### Deploying to GitHub Pages

Two front-ends, **two separate Pages sites in two repos**, cross-linked in their
headers. Splitting them avoids the gh-pages-root collision (each site owns its own
repo) and keeps the 832 MB of tiles out of the browse-site repo. Both deploy
scripts live here; each force-pushes an orphan `gh-pages` (one commit, no history
bloat).

| Front-end | Command | Repo / URL | Size | Notes |
|---|---|---|--:|---|
| DeepZoom **mosaic** | `./deploy_mosaic.sh` | `jblowe/ggm-mosaic` → `…/ggm-mosaic/` | ~832 MB | self-contained (viewer + tiles, same-origin, no CORS); fits the 1 GB Pages cap at the default `--row-height 2200`. Built here, pushed to the ggm-mosaic repo. |
| **browse-site** | `./deploy_site.sh` | `jblowe/ggm-images` → `…/ggm-images/` | ~9 MB | images load from S3 (below) |

Cross-links: the browse-site header links to **Zoom mosaic ↗**; the mosaic viewer
links back to **Browse by location ↗**.

One-time, per repo: **Settings → Pages → branch `gh-pages` / `(root)`** → live at
`https://jblowe.github.io/ggm-images/` and `https://jblowe.github.io/ggm-mosaic/`.

### Browse-site images (public-read S3)

The browse-site is tiny but references ~36k thumbnails, so those live on S3, served
**public-read** (these are public archive photos). `IMG_BASE` in `site/app.js`
points straight at the S3 endpoint:

```sh
# sync the thumbnails as-is (idempotent; ~2.6 GB, ~42k objects)
aws s3 sync ~/image_repos/ggm-images s3://ggm-thumbnails/ggm-thumbs/ \
    --exclude "*" --include "*.thumbnail.jpg" --size-only
# bucket public-read for the prefix:
#   Block Public Access: BlockPublicPolicy=false, RestrictPublicBuckets=false
#   bucket policy: Principal "*", s3:GetObject on  arn:aws:s3:::ggm-thumbnails/ggm-thumbs/*
# site/app.js:
#   const IMG_BASE = "https://ggm-thumbnails.s3.us-west-2.amazonaws.com/ggm-thumbs/";
```

> **CloudFront note (cautionary):** a private bucket + CloudFront **OAC** was
> attempted and abandoned — S3 rejected the OAC-signed requests with `403 AccessDenied`
> in a way that never resolved (even after recreating the OAC and removing it). The
> public-read S3 endpoint works directly. For a CDN later, stand up a **fresh**
> distribution with a *plain public-S3 origin* (no OAC) and repoint `IMG_BASE` at it.

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
| `build_site.py` | Emit the static browse-site manifests (`site/locations.json`, `site/extras.json`). |
| `report.py` | Census → `report.md`; refreshes `recovered.tsv`, `still_parked.txt`. |
| `master_list.py` | Per-photo census → `build/master_list.tsv` (included/excluded, status, locke, submosaic, location, nfd_differs). |
| `build_authority.py` | Bootstrap/validate canonical names (variant-merge stats). Standalone — no dedup/recovery. |
| `mine_prefixes.py` | Mine candidate connectives from parked photos. |
| `deploy_mosaic.sh` | Publish the DeepZoom mosaic (viewer + tiles) to the **`jblowe/ggm-mosaic`** gh-pages. |
| `deploy_site.sh` | Publish the browse-site to this repo's (**`ggm-images`**) gh-pages. |

## Artifacts (in `build/`, git-ignored)

| File | Meaning |
|---|---|
| `gm.dzi` + `gm_files/` | The DeepZoom tile pyramid. |
| `recovered.tsv` | Parked photos pulled into the mosaic by wordspotting (review). |
| `still_parked.txt` | Photos still excluded (`location · filename`) — targets for further recovery tuning. |
| `report.md` | Census: included/excluded, by city, per-Locke counts. |
| `master_list.tsv` | Per-photo join: path, included, status, locke, submosaic, location, nfd_differs. |
| `site/locations.json`, `site/extras.json` | Browse-site manifests (from `build_site.py`). |
| `authority.tsv`, `authority_excluded.txt` | Output of `build_authority.py`. |

---

## Key parameters (`build_mosaic.py`)

| Flag | Default | Effect |
|---|---|---|
| `--photo-height` | 720 | Working height per photo (detail vs memory; source maxes ~1030). |
| `--row-height` | 2200 | Justified row height — drives canvas size / pixels-per-photo. Default lands ~831 MB of tiles, under the 1 GB Pages cap. |
| `--quality` | 90 | JPEG tile quality. |
| `--no-dedup`, `--no-recover` | (off) | Disable de-duplication / wordspot recovery. |

Detail vs. size: canvas size scales with `--row-height` (not `--photo-height`,
which is free sharpness). Push `--row-height` higher for more detail, but past
~2400 the tiles exceed the 1 GB Pages cap — then host them on S3 instead.

---

## Notes on the source data

- Thumbnails round-trip to their originals: strip `.thumbnail.jpg` from a thumbnail
  path to get the original's path/stem (the original's extension varies —
  `.jpg`/`.JPG`/`.tif` — so locate it as `stem.*`).
- The repo was once tagged with a literal `" (nfc)"` Unicode marker; that has been
  cleaned up so thumbnail names match the (NFD) originals. Filenames are now
  consistent, and the parser NFD-normalizes anyway for robustness.
