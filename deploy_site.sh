#!/usr/bin/env bash
# Publish the static browse-site (site/) to the gh-pages branch for GitHub Pages.
#
# gh-pages holds ONLY the site at its ROOT (index.html, extras.html, style.css,
# app.js, and the two JSON manifests). The manifests are git-ignored on main, but
# we copy them straight in here, so they ship anyway. Images are NOT in this
# branch -- they load from IMG_BASE (S3/CloudFront) in site/app.js.
#
# Idempotent: builds the manifests in a throwaway orphan branch inside a temp
# worktree, then force-pushes it to origin/gh-pages -- so it doesn't matter
# whether a local/remote gh-pages branch already exists.
#
# One-time: enable Pages on branch gh-pages, folder / (root):
#   Settings -> Pages, or:  gh api -X POST repos/jblowe/ggm-images/pages \
#                              -f 'source[branch]=gh-pages' -f 'source[path]=/'
#
# Usage:  ./deploy_site.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "regenerating manifests ..."
./.venv/bin/python build_site.py >/dev/null

FILES="index.html extras.html style.css app.js locations.json extras.json"
for f in $FILES; do
  [ -f "site/$f" ] || { echo "missing site/$f"; exit 1; }
done

git worktree prune
TMP=__ghpages_deploy
WT=$(mktemp -d)
echo "staging in $WT ..."
git worktree add --detach "$WT" >/dev/null
(
  cd "$WT"
  git branch -D "$TMP" 2>/dev/null || true
  git checkout --orphan "$TMP"
  git rm -rf . >/dev/null 2>&1 || true       # also drops .gitignore -> JSONs ship
)
for f in $FILES; do cp "site/$f" "$WT/"; done
touch "$WT/.nojekyll"
(
  cd "$WT"
  git add -A
  git -c user.name="John B. Lowe" -c user.email="johnblowe@gmail.com" \
      commit -q -m "Publish browse-site $(date -u +%Y-%m-%dT%H:%MZ)"
  git push -f origin "HEAD:gh-pages"          # force-push regardless of existing gh-pages
)
git worktree remove --force "$WT"
git branch -D "$TMP" 2>/dev/null || true
echo "deployed -> https://jblowe.github.io/ggm-images/  (enable Pages on gh-pages / if not already)"
