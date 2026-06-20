#!/usr/bin/env bash
# Publish the static browse-site (site/) to the gh-pages branch for GitHub Pages.
#
# gh-pages is an ORPHAN branch that we reset each deploy and that holds ONLY the
# site at its ROOT (index.html, extras.html, style.css, app.js, and the two JSON
# manifests). The manifests are git-ignored on main, but we copy them straight
# into the branch here, so they ship even though they aren't tracked on main.
#
# Images are NOT in this branch -- they load from CloudFront via IMG_BASE in
# site/app.js. So this branch stays tiny (~9 MB).
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

for f in index.html extras.html style.css app.js locations.json extras.json; do
  [ -f "site/$f" ] || { echo "missing site/$f"; exit 1; }
done

WT=$(mktemp -d)
echo "staging gh-pages in $WT ..."
git worktree add --detach "$WT" >/dev/null
(
  cd "$WT"
  git checkout --orphan gh-pages
  git rm -rf . >/dev/null 2>&1 || true     # also drops .gitignore -> JSONs not ignored here
)

cp site/index.html site/extras.html site/style.css site/app.js \
   site/locations.json site/extras.json "$WT/"
touch "$WT/.nojekyll"                       # don't let Jekyll process the files

(
  cd "$WT"
  git add -A
  git -c user.name="John B. Lowe" -c user.email="johnblowe@gmail.com" \
      commit -q -m "Publish browse-site $(date -u +%Y-%m-%dT%H:%MZ)"
  git push -f origin gh-pages
)

git worktree remove --force "$WT"
echo "deployed -> https://jblowe.github.io/ggm-images/  (enable Pages on gh-pages / if not already)"
