"use strict";
// AI writing help on the page: improving one bullet, and the cover letter.
// Uses the helpers and `state` defined in app.js.

const PLACEHOLDER_RE = /\[[^\]\n]{0,60}\b(?:month|year|date|rating|number|N|X|link|url|your|insert|tbd|todo|e\.g\.|percent|amount|name|company|role|title)\b[^\]\n]{0,60}\]/gi;

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = text;
  return d.innerHTML;
}

function withPlaceholders(text) {
  return escapeHtml(text).replace(PLACEHOLDER_RE, (m) => `<mark class="placeholder">${m}</mark>`);
}

// ---------- Improve one bullet ----------

let improveLi = null;
let improveRequest = 0;

// Clicking a bullet (e.g. to type in it) only shows a small "Improve" button beside it;
// the full set of options opens when that's clicked.
function showImproveChip(li) {
  if (improveLi && improveLi !== li) closeImprove();
  if (!$("improve-pop").hidden && improveLi === li) return;
  const chip = $("improve-chip");
  const frame = document.querySelector(".paper-frame").getBoundingClientRect();
  const r = li.getBoundingClientRect();
  chip.hidden = false;
  const lineHeight = parseFloat(getComputedStyle(li).lineHeight) || 16;
  chip.style.top = `${r.top - frame.top + lineHeight / 2 - chip.offsetHeight / 2}px`;
  chip.style.left = `${frame.width - chip.offsetWidth - 10}px`;  // in the page's right margin
  improveLi = li;
}

function openImprove(li) {
  if (improveLi && improveLi !== li) improveLi.classList.remove("improving");
  improveLi = li;
  $("improve-chip").hidden = true;
  li.classList.add("improving");
  const pop = $("improve-pop");
  const frame = document.querySelector(".paper-frame").getBoundingClientRect();
  const r = li.getBoundingClientRect();
  pop.hidden = false;
  pop.style.top = `${r.bottom - frame.top + 6}px`;
  pop.style.left = `${Math.max(8, Math.min(r.left - frame.left, frame.width - pop.offsetWidth - 8))}px`;
  $("improve-job").hidden = !(state.target || "").trim();
  $("improve-ask").hidden = true;
  $("improve-results").replaceChildren();
}

function closeImprove() {
  improveRequest++;  // ignore any answer still on its way
  $("improve-pop").hidden = true;
  $("improve-chip").hidden = true;
  improveLi?.classList.remove("improving");
  improveLi = null;
}

async function requestImprove(mode, instruction = "") {
  if (!improveLi) return;
  const request = ++improveRequest;
  const results = $("improve-results");
  const thinking = el("div", "thinking");
  thinking.append(el("div", "spinner"),
                  el("span", "", state.ai_status.local ? "Thinking… (a local model can take a minute)" : "Thinking…"));
  results.replaceChildren(thinking);
  try {
    const { suggestions } = await api("POST", "/api/improve", { text: improveLi.innerText, mode, instruction });
    if (request !== improveRequest) return;
    results.replaceChildren(...suggestions.map((s) => {
      const b = button("", "suggestion", () => applySuggestion(s), "Use this version");
      b.innerHTML = withPlaceholders(s);
      return b;
    }));
  } catch (err) {
    if (request === improveRequest) results.replaceChildren(el("div", "thinking", err.message));
  }
}

function applySuggestion(text) {
  const li = improveLi;
  li.innerHTML = withPlaceholders(text);
  closeImprove();
  $("cv").dispatchEvent(new Event("input"));  // saves the edit and refreshes the checks
  li.classList.add("flash");
  setTimeout(() => li.classList.remove("flash"), 1600);
}

$("cv").addEventListener("click", (e) => {
  const li = e.target.closest(".cv-entry li");
  if (li && state?.ai_enabled) showImproveChip(li);
  else closeImprove();
});
document.addEventListener("click", (e) => {
  if (improveLi && !e.target.closest("#improve-pop") && !e.target.closest("#improve-chip") && !e.target.closest("#cv")) {
    closeImprove();
  }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeImprove(); });
document.querySelectorAll("#improve-pop [data-mode]").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.mode === "custom") {
    $("improve-ask").hidden = false;
    $("improve-instruction").focus();
  } else requestImprove(b.dataset.mode);
}));
$("improve-ask").addEventListener("submit", (e) => {
  e.preventDefault();
  const instruction = $("improve-instruction").value.trim();
  if (instruction) requestImprove("custom", instruction);
});
document.querySelector(".improve-close").addEventListener("click", closeImprove);
$("improve-chip").addEventListener("mousedown", (e) => e.preventDefault());  // keep the text cursor where it is
$("improve-chip").addEventListener("click", () => { if (improveLi) openImprove(improveLi); });

// ---------- Cover letter ----------

let letterTimer = null;
let savingLetter = Promise.resolve();

function renderLetter() {
  const letter = state.letter || {};
  const page = $("letter");
  const active = state.active;
  const forWhom = active.id === "general" ? "your general CV" : active.name;
  const phd = active.kind === "phd";
  const kind = phd ? "Statement of purpose" : "Cover letter";
  document.querySelector('.tab[data-tab="letter"]').textContent = phd ? "Statement of purpose" : "Cover letter";
  $("letter-for").textContent = letter.html
    ? `${kind} for ${forWhom}${letter.edited ? " · edits saved" : ""}. Click to edit.`
    : `${kind} for ${forWhom}`;
  if (document.activeElement !== page || page.dataset.version !== active.id) {
    if (document.activeElement === page) page.blur();
    page.innerHTML = letter.html || "";
    page.dataset.version = active.id;
  }
  page.hidden = !letter.html;
  page.classList.remove("t-classic", "t-modern", "t-minimal");
  page.classList.add(`t-${state.settings.template}`);
  if (state.settings.template === "modern") page.style.setProperty("--cv-accent", state.settings.accent);
  else page.style.removeProperty("--cv-accent");
  page.classList.toggle("letter-us", state.settings.page_size === "letter");
  $("letter-empty").hidden = !!letter.html;
  document.querySelector("#letter-empty h3").textContent = phd ? "No statement of purpose yet" : "No cover letter yet";
  $("letter-empty-text").textContent = phd
    ? `A statement of purpose for ${forWhom}, written from your memory: your research interests, your research experience with its methods and results, why this programme, and your goals. Every claim is something you've actually done; gaps are marked for you to fill in.`
    : active.id === "general" && !(state.target || "").trim()
      ? "For the best letter, create an application in the Applications tab with the job ad, then write its letter here. You can also write a general one now."
      : `It's written from your memory and the job ad for ${forWhom}, so every claim is something you've actually done.`;
  $("letter-write").textContent = letter.html ? "Rewrite" : phd ? "Write statement of purpose" : "Write cover letter";
  $("letter-write").disabled = !state.ai_enabled;
  $("letter-pdf").disabled = !letter.html;
  $("letter-docx").disabled = !letter.html;
  if (letter.tone) $("letter-tone").value = letter.tone;
}

async function writeLetter() {
  if (state.letter?.edited && !confirm("Rewriting replaces your edits to this letter. Continue?")) return;
  const what = state.active.kind === "phd" ? "statement of purpose" : "cover letter";
  await withBusy(busyText(`Writing your ${what}…`), async () => {
    render(await api("POST", "/api/letter", { tone: $("letter-tone").value }));
    showNotice("");
  });
}

let pendingLetterSave = null;

$("letter").addEventListener("input", () => {
  clearTimeout(letterTimer);
  const version = state.active.id;
  const html = () => $("letter").innerHTML;
  pendingLetterSave = () => {
    pendingLetterSave = null;
    const saved = html();
    savingLetter = api("POST", "/api/letter/edits", { html: saved, version })
      .then(() => { if (state.active.id === version) state.letter = { ...state.letter, html: saved, edited: true }; })
      .catch((err) => showNotice(err.message, true));
    return savingLetter;
  };
  letterTimer = setTimeout(() => pendingLetterSave && pendingLetterSave(), 800);
});

async function flushLetter() {
  clearTimeout(letterTimer);
  if (pendingLetterSave) await pendingLetterSave();
  await savingLetter;
}
$("letter").addEventListener("paste", (e) => {
  e.preventDefault();
  document.execCommand("insertText", false, e.clipboardData.getData("text/plain"));
});
$("letter-write").addEventListener("click", writeLetter);
$("letter-pdf").addEventListener("click", async () => {
  await flushLetter();
  const ok = await downloadFile("/api/export/letter.pdf", "Making your PDF…");
  if (!ok && $("notice").textContent.includes("No Chrome")) {
    showNotice("No Chrome, Edge or Brave browser was found, so the print window opened instead. Choose 'Save as PDF'.");
    printFallback("Cover Letter");
  }
});
$("letter-docx").addEventListener("click", async () => {
  await flushLetter();
  downloadFile("/api/export/letter.docx", "Making your Word document…");
});
