"use strict";
// Compare two CVs side by side and highlight what changed, word by word.
// Uses the helpers and `state` defined in app.js.

// Pieces of a CV that are compared with each other (a bullet with a bullet, a title with a title…).
const BLOCKS = [".cv-headline", ".cv-summary", ".cv-entry-title", ".cv-entry-org", ".cv-entry-desc",
                ".cv-entry li", ".cv-items li"];

function words(text) {
  return text.trim().split(/\s+/).filter(Boolean);
}

function similarity(a, b) {
  const A = new Set(words(a.toLowerCase())), B = new Set(words(b.toLowerCase()));
  if (!A.size && !B.size) return 1;
  let common = 0;
  for (const w of A) if (B.has(w)) common++;
  return common / new Set([...A, ...B]).size;
}

// Word-level diff (longest common subsequence). Returns [{word, kind: "same" | "add" | "del"}].
function diffWords(oldText, newText) {
  const a = words(oldText), b = words(newText);
  const n = a.length, m = b.length;
  const lcs = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ word: a[i], kind: "same" }); i++; j++; }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) out.push({ word: a[i++], kind: "del" });
    else out.push({ word: b[j++], kind: "add" });
  }
  while (i < n) out.push({ word: a[i++], kind: "del" });
  while (j < m) out.push({ word: b[j++], kind: "add" });
  return out;
}

function markup(parts, keep) {
  return parts.filter((p) => keep.includes(p.kind)).map((p) => {
    const w = escapeHtml(p.word);
    if (p.kind === "add") return `<ins class="diff-add">${w}</ins>`;
    if (p.kind === "del") return `<del class="diff-del">${w}</del>`;
    return w;
  }).join(" ");
}

function blocksOf(root) {
  return BLOCKS.flatMap((sel) => [...root.querySelectorAll(sel)].map((el) => ({ el, sel, text: el.textContent })));
}

// Mark up `left` (the other CV) and `right` (this CV) in place; returns counts for the summary.
function highlightDifferences(left, right) {
  const oldBlocks = blocksOf(left), newBlocks = blocksOf(right);
  const used = new Set();
  const stats = { changed: 0, added: 0, removed: 0 };
  for (const nb of newBlocks) {
    let best = null, bestScore = 0;
    for (const ob of oldBlocks) {
      if (used.has(ob) || ob.sel !== nb.sel) continue;
      const score = similarity(ob.text, nb.text);
      if (score > bestScore) { best = ob; bestScore = score; }
    }
    if (!best || bestScore < 0.3) {
      nb.el.classList.add("diff-new-block");
      stats.added++;
      continue;
    }
    used.add(best);
    if (best.text.trim() === nb.text.trim()) continue;
    const parts = diffWords(best.text, nb.text);
    nb.el.innerHTML = markup(parts, ["same", "add"]);
    best.el.innerHTML = markup(parts, ["same", "del"]);
    stats.changed++;
  }
  for (const ob of oldBlocks) {
    if (!used.has(ob) && ob.text.trim()) {
      ob.el.classList.add("diff-gone-block");
      stats.removed++;
    }
  }
  return stats;
}

function styleLike(page) {
  page.classList.remove("t-classic", "t-modern", "t-minimal");
  page.classList.add(`t-${state.settings.template}`);
  if (state.settings.template === "modern") page.style.setProperty("--cv-accent", state.settings.accent);
}

async function showCompare(otherId) {
  const others = [{ id: "general", name: "General CV" }, ...state.versions].filter((v) => v.id !== state.active.id);
  if (!others.length) return;
  otherId = otherId && others.some((o) => o.id === otherId) ? otherId : others[0].id;
  await flushEdits();
  let other;
  try {
    other = await api("GET", `/api/versions/${otherId}/cv`);
  } catch (err) {
    showNotice(err.message, true);
    return;
  }
  const select = $("compare-other");
  select.replaceChildren(...others.map((o) => new Option(o.name, o.id)));
  select.value = otherId;
  $("compare-this").textContent = state.active.name;
  $("compare-left-label").textContent = other.name;
  $("compare-right-label").textContent = `${state.active.name} (this CV)`;

  const left = $("compare-left"), right = $("compare-right");
  left.innerHTML = other.html || "<p>This CV hasn't been built yet.</p>";
  right.innerHTML = cvHtml();
  [left, right].forEach(styleLike);
  const stats = highlightDifferences(left, right);
  const bits = [stats.changed && `${stats.changed} reworded`, stats.added && `${stats.added} added`,
                stats.removed && `${stats.removed} removed`].filter(Boolean);
  $("compare-stats").textContent = bits.length ? `· ${bits.join(", ")}` : "· no differences in the wording";

  $("compare-view").hidden = false;
  $("paper-wrap").hidden = true;
  $("design-bar").hidden = true;
  $("check-panel").hidden = true;
}

function hideCompare() {
  $("compare-view").hidden = true;
  $("paper-wrap").hidden = false;
  render(state);
}

$("compare").addEventListener("click", () => showCompare());
$("compare-other").addEventListener("change", (e) => showCompare(e.target.value));
$("compare-close").addEventListener("click", hideCompare);
$("version-select").addEventListener("change", () => { if (!$("compare-view").hidden) hideCompare(); });
