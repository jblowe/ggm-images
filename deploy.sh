#!/usr/bin/env bash
# Publish the built mosaic to the gh-pages branch.
#
# Strategy: gh-pages is an ORPHAN branch that we reset on every deploy, so the
# (large, regenerated) tile set never accumulates in history. Code/params live
# on main; only the publishable artifacts go to gh-pages.
#
# Publishes: index.html, openseadragon/, gm.dzi, gm_files/, .nojekyll
#
# Usage:  ./deploy.sh            # build/gm.dzi + build/gm_files must exist
set -euo pipefail
cd "$(dirname "$0")"

OUT=build/gm
[ -f "$OUT.dzi" ] || { echo "missing $OUT.dzi — run build_mosaic.py first"; exit 1; }
[ -d "${OUT}_files" ] || { echo "missing ${OUT}_files — run build_mosaic.py first"; exit 1; }

REMOTE_URL=$(git remote get-url origin)
WT=$(mktemp -d)
echo "staging gh-pages in $WT ..."

# fresh orphan branch in a temp worktree
git worktree add --detach "$WT" >/dev/null
(
  cd "$WT"
  git checkout --orphan gh-pages
  git rm -rf . >/dev/null 2>&1 || true
)

cp index.html "$WT/"
cp -R openseadragon "$WT/"
cp "$OUT.dzi" "$WT/gm.dzi"
cp -R "${OUT}_files" "$WT/gm_files"
touch "$WT/.nojekyll"          # stop Pages/Jekyll from processing tile folders

(
  cd "$WT"
  git add -A
  git -c user.name="John B. Lowe" -c user.email="johnblowe@gmail.com" \
      commit -q -m "Publish mosaic $(date -u +%Y-%m-%dT%H:%MZ)"
  git push -f origin gh-pages
)

git worktree remove --force "$WT"
echo "deployed. enable Pages on branch gh-pages (/) if not already:"
echo "  https://jblowe.github.io/ggm-images/"
