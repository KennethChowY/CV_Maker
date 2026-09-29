"use strict";
// Layout helpers shared by the on-screen preview and the downloaded PDF.
// No dependencies, so the PDF page can include this file as it is.

window.CVLayout = (() => {
  const MAX_TIGHTEN_PX = 0.35;  // at most this much less space between letters; not noticeable at CV sizes
  const SPILL_SHARE = 0.2;      // a last line shorter than 20% of the width (3–4 words) counts as a spill-over

  function lineBoxes(el) {
    const range = document.createRange();
    range.selectNodeContents(el);
    const lines = [];
    for (const r of range.getClientRects()) {
      if (r.width < 1) continue;
      const line = lines.find((l) => Math.abs(l.top - r.top) < r.height / 2);
      if (line) {
        line.left = Math.min(line.left, r.left);
        line.right = Math.max(line.right, r.right);
      } else lines.push({ top: r.top, left: r.left, right: r.right });
    }
    return lines.sort((a, b) => a.top - b.top);
  }

  // A bullet (or paragraph) whose last line holds only a word or two.
  function spills(el) {
    const lines = lineBoxes(el);
    if (lines.length < 2) return false;
    const width = el.getBoundingClientRect().width || 1;
    const last = lines[lines.length - 1];
    return (last.right - last.left) / width < SPILL_SHARE;
  }

  // Pull a stray last word back up by tightening letter spacing a touch, only where that works.
  function tighten(root) {
    const blocks = root.querySelectorAll("li, .cv-summary, .cv-entry-desc, p");
    for (const el of blocks) {
      if (el.dataset.tight) {
        el.style.letterSpacing = "";
        delete el.dataset.tight;
      }
    }
    for (const el of blocks) {
      if (!spills(el)) continue;
      const before = lineBoxes(el).length;
      for (let px = 0.1; px <= MAX_TIGHTEN_PX + 1e-9; px += 0.05) {
        el.style.letterSpacing = `-${px.toFixed(2)}px`;
        if (lineBoxes(el).length < before) {
          el.dataset.tight = "1";
          break;
        }
      }
      if (!el.dataset.tight) el.style.letterSpacing = "";
    }
  }

  let pxPerMm = 0;
  function mm(n) {
    if (!pxPerMm) {
      const probe = document.createElement("div");
      probe.style.cssText = "position:absolute;visibility:hidden;width:100mm";
      document.body.append(probe);
      pxPerMm = probe.getBoundingClientRect().width / 100;
      probe.remove();
    }
    return n * pxPerMm;
  }

  function outerHeight(el) {
    const cs = getComputedStyle(el);
    return el.getBoundingClientRect().height + parseFloat(cs.marginTop) + parseFloat(cs.marginBottom);
  }

  // Places where a new page may start, following the same rules as cv.css: never after a
  // heading, keep an entry's title with its first two bullets, never leave one bullet alone,
  // and don't split short entries or list sections.
  function candidates(root, y) {
    const out = [];
    const sections = [...root.querySelectorAll("section.cv-section")].filter((s) => !s.hidden);
    sections.forEach((section, i) => {
      if (i > 0) out.push({ y: y(section), el: section, entry: null });
      [...section.querySelectorAll(":scope > .cv-entry")].forEach((entry, j) => {
        if (j > 0) out.push({ y: y(entry), el: entry, entry: null });
        if (!entry.classList.contains("long")) return;
        const items = [...entry.querySelectorAll(":scope > ul > li")];
        items.forEach((li, k) => {
          if (k >= 2 && k < items.length - 1) out.push({ y: y(li), el: li, entry });
        });
      });
    });
    return out;
  }

  // Plan the pages. Pages after the first also hold a running header, and a "continued" line
  // when they start part-way through an entry, so they have that much less room.
  function plan(root, pageHeight, extra = { header: 0, cont: 0 }) {
    const origin = root.getBoundingClientRect().top + parseFloat(getComputedStyle(root).paddingTop);
    const y = (el) => el.getBoundingClientRect().top - origin;
    const cands = candidates(root, y);
    let end = 0;
    for (const child of root.children) {
      if (child.hidden || child.dataset.auto) continue;
      end = Math.max(end, child.getBoundingClientRect().bottom - origin);
    }
    const breaks = [];
    let pageStart = 0;
    let used = 0;  // room taken on the current page by the running header and "continued" line
    while (end - pageStart + used > pageHeight + 0.5 && breaks.length < 50) {
      const limit = pageStart + pageHeight - used;
      const fits = cands.filter((c) => c.y > pageStart + 1 && c.y <= limit);
      const pick = fits.length ? fits[fits.length - 1] : { y: limit, el: null, entry: null };  // nothing fits: cut at the edge
      breaks.push(pick);
      pageStart = pick.y;
      used = extra.header + (pick.entry ? extra.cont : 0);
    }
    return { breaks, end, lastPageHeight: end - pageStart + used };
  }

  function pageHeader(name, page, total) {
    const head = document.createElement("div");
    head.className = "cv-pagehead";
    head.dataset.auto = "head";
    head.contentEditable = "false";
    const left = document.createElement("span");
    left.textContent = name;
    const right = document.createElement("span");
    right.textContent = `Page ${page} of ${total}`;
    head.append(left, right);
    return head;
  }

  function continuedLine(entry) {
    const line = document.createElement("div");
    line.className = "cv-cont";
    line.dataset.auto = "cont";
    line.contentEditable = "false";
    const title = entry?.querySelector(".cv-entry-title")?.textContent.trim() || "";
    const org = entry?.querySelector(".cv-entry-org")?.textContent.trim() || "";
    const strong = document.createElement("span");
    strong.className = "cv-entry-title";
    strong.textContent = title;
    line.append(strong, `${org ? ` · ${org}` : ""} (continued)`);
    return line;
  }

  // Heights of the running header and "continued" line, measured in place.
  function extras(root) {
    const head = pageHeader("Name", 2, 2);
    const cont = continuedLine(null);
    root.append(head, cont);
    const sizes = { header: outerHeight(head), cont: outerHeight(cont) };
    head.remove();
    cont.remove();
    return sizes;
  }

  // Undo paginate(): take out the headers and "continued" lines and rejoin split lists.
  function unpaginate(root) {
    root.querySelectorAll('[data-auto="head"], [data-auto="cont"]').forEach((n) => n.remove());
    root.querySelectorAll('ul[data-auto="split"]').forEach((rest) => {
      const before = rest.previousElementSibling;
      if (before && before.tagName === "UL") {
        before.append(...rest.childNodes);
        rest.remove();
      } else rest.removeAttribute("data-auto");
    });
  }

  // Put in real page breaks for printing: each later page starts with a running header
  // ("Name · Page 2 of 3"), and a "continued" line when it picks up part-way through an entry.
  function paginate(root, pageHeight, name) {
    unpaginate(root);
    const planned = plan(root, pageHeight, extras(root));
    const total = planned.breaks.length + 1;
    planned.breaks.forEach((b, i) => {
      if (!b.el) return;  // content taller than a page: let the browser cut it
      const head = pageHeader(name, i + 2, total);
      if (!b.entry) {
        b.el.before(head);
        return;
      }
      const list = b.el.parentElement;
      const rest = document.createElement("ul");
      rest.dataset.auto = "split";
      let node = b.el;
      while (node) {
        const next = node.nextSibling;
        rest.append(node);
        node = next;
      }
      list.after(head, continuedLine(b.entry), rest);
    });
    return total;
  }

  return { tighten, spills, plan, extras, paginate, unpaginate, mm };
})();
