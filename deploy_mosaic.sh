#!/usr/bin/env bash
# Publish the DeepZoom mosaic to the gh-pages branch for GitHub Pages.
#
# The mosaic is fully self-contained and same-origin (viewer + tiles together),
# so it runs on Pages with no server and no CORS. It must stay under the 1 GB
# Pages cap -- rebuild with a smaller --row-height if du says otherwise.
#
# Publishes to the branch ROOT: index.html (OpenSeadragon viewer), openseadragon/,
# gm.dzi, gm_files/. gh-pages is an orphan branch reset each deploy (one commit),
# so the 700 MB+ of tiles never accumulate in history.
#
# NB: deploy_site.sh also targets gh-pages root -- they're mutually exclusive for
# now. (Hosting both at once would mean subdirs + a landing page; revisit later.)
#
# One-time: Settings -> Pages -> branch gh-pages / (root).
#
# Usage:  ./deploy_mosaic.sh
set -euo pipefail
cd "$(dirname "$0")"

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
  git push -f origin "HEAD:gh-pages"
)
git worktree remove --force "$WT"
git branch -D "$TMP" 2>/dev/null || true
echo "deployed mosaic -> https://jblowe.github.io/ggm-images/  (enable Pages on gh-pages / if not already)"
