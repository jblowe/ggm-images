// Shared 3-pane browser for the location and Extras pages.
// Configure where the thumbnails are served from:
//   dev  : a local symlink "imgbase" -> ~/image_repos/ggm-images
//   prod : your CloudFront base, e.g. "https://dXXXX.cloudfront.net/ggm/thumbs/"
// const IMG_BASE = "imgbase/";
const IMG_BASE = "https://d3900tbyp16q24.cloudfront.net/ggm-thumbs/";

function imgUrl(src) {
  // encode each path segment (spaces, unicode, commas) but keep the slashes
  return IMG_BASE + src.split("/").map(encodeURIComponent).join("/");
}

async function initApp(dataUrl) {
  const data = await (await fetch(dataUrl)).json();
  const groups = data.groups;
  document.querySelector("#title").textContent = data.title;
  document.title = data.title;

  const nav = document.querySelector("#nav-list");
  const filter = document.querySelector("#filter");
  const main = document.querySelector("#stage");

  // build nav (optionally grouped by the part of `sub` before the dot)
  function renderNav(q = "") {
    nav.innerHTML = "";
    let lastGroup = null;
    const ql = q.toLowerCase();
    groups.forEach((g, i) => {
      if (ql && !g.title.toLowerCase().includes(ql)) return;
      // group header only when there's a city prefix (locations page), not Extras
      const grp = g.sub.includes("·") ? g.sub.split("·")[0].trim() : "";
      if (grp && grp !== lastGroup) {
        lastGroup = grp;
        const h = document.createElement("div");
        h.className = "nav-group"; h.textContent = grp; nav.appendChild(h);
      }
      const el = document.createElement("div");
      el.className = "nav-item"; el.dataset.idx = i;
      // show the Locke number next to the location name (locations page only)
      const lk = /^[KPB]\d/.test(g.id) ? ` <span class="lk">${g.id}</span>` : "";
      el.innerHTML = `<span>${escapeHtml(g.title)}${lk}</span><span class="n">${g.count}</span>`;
      el.onclick = () => { location.hash = "#" + encodeURIComponent(g.id); };
      nav.appendChild(el);
    });
  }

  function show(idx) {
    const g = groups[idx];
    document.querySelectorAll(".nav-item").forEach(n =>
      n.classList.toggle("active", +n.dataset.idx === idx));
    const subtitle = [g.sub, `${g.count} photos`].filter(Boolean).join(" — ");
    main.innerHTML =
      `<h2>${escapeHtml(g.title)}</h2><div class="stage-sub">${escapeHtml(subtitle)}</div>`;
    const m = document.createElement("div");
    m.className = "masonry";
    g.photos.forEach(p => {
      const fig = document.createElement("figure");
      fig.innerHTML =
        `<img loading="lazy" src="${imgUrl(p.src)}" alt="${escapeHtml(p.cap)}">` +
        `<figcaption>${escapeHtml(p.cap)}</figcaption>`;
      fig.querySelector("img").onclick = () => lightbox(p);
      m.appendChild(fig);
    });
    main.appendChild(m);
    main.scrollTop = 0;
  }

  function route() {
    const id = decodeURIComponent((location.hash || "").slice(1));
    const idx = id ? groups.findIndex(g => String(g.id) === id) : -1;
    if (idx >= 0) show(idx);
    else main.innerHTML = `<p class="placeholder">Select an item on the left (${groups.length} available).</p>`;
  }

  filter.oninput = () => renderNav(filter.value);
  window.addEventListener("hashchange", route);
  renderNav();
  route();
}

function lightbox(p) {
  const lb = document.querySelector("#lb");
  lb.querySelector("img").src = imgUrl(p.src);
  lb.querySelector(".cap").textContent = p.cap;
  lb.classList.add("open");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

document.querySelector("#lb").onclick = () =>
  document.querySelector("#lb").classList.remove("open");
