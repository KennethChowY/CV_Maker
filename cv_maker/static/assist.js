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

function openImprove(li) {
  if (improveLi && improveLi !== li) improveLi.classList.remove("improving");
  improveLi = li;
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
  if (li && state?.ai_enabled) openImprove(li);
  else closeImprove();
});
document.addEventListener("click", (e) => {
  if (improveLi && !e.target.closest("#improve-pop") && !e.target.closest("#cv")) closeImprove();
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
