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

  // Where the pages will break, as offsets (px) from the top of the content, following the
  // same rules as cv.css: never after a heading, keep an entry's title with its first two
  // bullets, never leave one bullet alone, and don't split short entries or list sections.
  function breaks(root, pageHeight) {
    const origin = root.getBoundingClientRect().top + parseFloat(getComputedStyle(root).paddingTop);
    const y = (el) => el.getBoundingClientRect().top - origin;
    const candidates = [];  // positions where a new page may start
    const sections = [...root.querySelectorAll("section.cv-section")].filter((s) => !s.hidden);
    sections.forEach((section, i) => {
      if (i > 0) candidates.push(y(section));
      const entries = [...section.querySelectorAll(":scope > .cv-entry")];
      entries.forEach((entry, j) => {
        if (j > 0) candidates.push(y(entry));
        if (!entry.classList.contains("long")) return;
        const items = [...entry.querySelectorAll(":scope > ul > li")];
        items.forEach((li, k) => {
          if (k >= 2 && k < items.length - 1) candidates.push(y(li));
        });
      });
    });
    let end = 0;
    for (const child of root.children) {
      if (child.hidden) continue;
      end = Math.max(end, child.getBoundingClientRect().bottom - origin);
    }
    const result = [];
    let pageStart = 0;
    while (end - pageStart > pageHeight + 0.5) {
      const limit = pageStart + pageHeight;
      const fits = candidates.filter((c) => c > pageStart + 1 && c <= limit);
      const at = fits.length ? fits[fits.length - 1] : limit;  // nothing fits: cut at the page edge
      result.push(at);
      pageStart = at;
    }
    return { breaks: result, end, lastPageHeight: end - pageStart };
  }

  return { tighten, breaks, spills };
})();
