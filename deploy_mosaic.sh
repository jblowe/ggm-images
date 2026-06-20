#!/usr/bin/env bash
# Publish the DeepZoom mosaic to the gh-pages branch for GitHub Pages.
#
# The mosaic is fully self-contained and same-origin (viewer + tiles together),
# so it runs on Pages with no server and no CORS. It must stay under the 1 GB
# Pages cap -- rebuild with a smaller --row-height if du says otherwise.
#
# The mosaic is its OWN Pages site, in a SEPARATE repo (jblowe/ggm-mosaic), so it
# never collides with the browse-site (this repo's gh-pages, via deploy_site.sh).
# We build the tiles here but push them to ggm-mosaic's gh-pages.
#
# Publishes to the branch ROOT: index.html (OpenSeadragon viewer), openseadragon/,
# gm.dzi, gm_files/. gh-pages is an orphan branch reset each deploy (one commit),
# so the 700 MB+ of tiles never accumulate in history.
#
# One-time: in jblowe/ggm-mosaic, Settings -> Pages -> branch gh-pages / (root).
#
# Usage:  ./deploy_mosaic.sh
set -euo pipefail
cd "$(dirname "$0")"

REMOTE="https://github.com/jblowe/ggm-mosaic.git"

[ -f build/gm.dzi ]   || { echo "build/gm.dzi missing -- run build_mosaic.py first"; exit 1; }
[ -d build/gm_files ] || { echo "build/gm_files missing -- run build_mosaic.py first"; exit 1; }
SIZE=$(du -sm build/gm_files | cut -f1)
echo "mosaic tiles: ${SIZE} MB"
[ "$SIZE" -lt 1000 ] || echo "WARNING: tiles are ${SIZE} MB (>1 GB) -- GitHub Pages may reject."

git worktree prune
TMP=__ghpages_mosaic
WT=$(mktemp -d)
echo "staging in $WT ..."
git worktree add --detach "$WT" >/dev/null
(
  cd "$WT"
  git branch -D "$TMP" 2>/dev/null || true
  git checkout --orphan "$TMP"
  git rm -rf . >/dev/null 2>&1 || true
)
cp index.html "$WT/"
cp -R openseadragon "$WT/openseadragon"
cp build/gm.dzi "$WT/gm.dzi"
cp -R build/gm_files "$WT/gm_files"
touch "$WT/.nojekyll"
(
  cd "$WT"
  git add -A
  git -c user.name="John B. Lowe" -c user.email="johnblowe@gmail.com" \
      commit -q -m "Publish mosaic $(date -u +%Y-%m-%dT%H:%MZ)"
  git push -f "$REMOTE" "HEAD:gh-pages"
)
git worktree remove --force "$WT"
git branch -D "$TMP" 2>/dev/null || true
echo "deployed mosaic -> https://jblowe.github.io/ggm-mosaic/  (enable Pages on gh-pages / in jblowe/ggm-mosaic if not already)"
