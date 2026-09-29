"use strict";
// Reviewing the memory, only when asked. Suggestions are shown with before and after;
// nothing changes until the person ticks some and clicks Apply.

let reviewSuggestions = [];

const FIELD_NAMES = {
  role: "Job title", organization: "Organisation", kind: "Type", location: "Location", start: "Start", end: "End",
  description: "Description", highlights: "Highlights", skills: "Skills", qualification: "Qualification",
  field: "Subject", institution: "Institution", grade: "Grade", thesis: "Final-year project or thesis",
  name: "Name", title: "Title", issuer: "Issuer", date: "Date", link: "Link",
};

function currentItem(s) {
  if (s.section === "skills") return { skills: state.memory.skills };
  return (state.memory[s.section] || []).find((x) => x.id === s.item_id) || {};
}

function showValue(value) {
  if (Array.isArray(value)) {
    if (value.length && typeof value[0] === "object") {
      return value.map((g) => `${g.category ? `${g.category}: ` : ""}${(g.skills || []).join(", ")}`).join("\n");
    }
    return value.map((x) => `• ${x}`).join("\n") || "(none)";
  }
  return String(value ?? "").trim() || "(empty)";
}

function suggestionCard(s) {
  const card = el("label", `review-item ${s.source}`);
  const box = el("input");
  box.type = "checkbox";
  box.dataset.id = s.id;
  box.addEventListener("change", updateReviewButtons);
  const body = el("div");
  const head = el("div", "review-title");
  head.append(el("strong", "", s.summary), el("span", "hint", ` · ${s.label}`));
  body.append(head);
  if (s.reason) body.append(el("div", "hint", s.reason));
  const before = currentItem(s);
  Object.entries(s.changes).forEach(([field, after]) => {
    const row = el("div", "review-diff");
    row.append(el("div", "field-label", FIELD_NAMES[field] || field),
               el("div", "was", showValue(before[field])), el("div", "now", showValue(after)));
    body.append(row);
  });
  if (s.remove_ids.length) body.append(el("div", "hint", "The duplicate entry is then removed."));
  s.warnings.forEach((w) => body.append(el("div", "hint warn", `⚠ ${w}`)));
  card.append(box, body);
  return card;
}

function renderReview() {
  const list = $("review-list");
  const rules = reviewSuggestions.filter((s) => s.source === "rule");
  const ai = reviewSuggestions.filter((s) => s.source === "ai");
  if (!reviewSuggestions.length) {
    list.replaceChildren(el("div", "check-item ok", "✓ Nothing to fix: your memory looks tidy."));
  } else {
    const parts = [];
    if (rules.length) {
      parts.push(el("h3", "", `Quick fixes (${rules.length}) · made by simple rules, reliable with any model`));
      parts.push(...rules.map(suggestionCard));
    }
    if (ai.length) {
      parts.push(el("h3", "", `AI suggestions (${ai.length}) · check each one; accept only what's true`));
      parts.push(...ai.map(suggestionCard));
    }
    list.replaceChildren(...parts);
  }
  $("review-select-rules").hidden = !rules.length;
  updateReviewButtons();
}

function ticked() {
  const ids = new Set([...$("review-list").querySelectorAll("input:checked")].map((b) => b.dataset.id));
  return reviewSuggestions.filter((s) => ids.has(s.id));
}

function updateReviewButtons() {
  const n = ticked().length;
  $("review-apply").disabled = !n;
  $("review-apply").textContent = n ? `Apply ${n} selected` : "Apply selected";
}

async function runReview() {
  const useAi = state.ai_enabled && $("review-ai").checked;
  $("review-panel").hidden = false;
  $("review-ai-wrap").hidden = !state.ai_enabled;
  const res = await withBusy(useAi ? busyText("Reviewing your memory…") : "Checking your memory…",
                             () => api("POST", "/api/memory/review", { ai: useAi }));
  if (!res) return;
  reviewSuggestions = res.suggestions;
  renderReview();
}

async function applyReview() {
  const chosen = ticked();
  if (!chosen.length) return;
  await withBusy("Updating your memory…", async () => {
    const next = await api("POST", "/api/memory/revise", { suggestions: chosen });
    render(next);
    showNotice(next.notice || "");
    const applied = new Set(chosen.map((s) => s.id));
    // What's left may no longer match the memory, so look again before offering it.
    reviewSuggestions = reviewSuggestions.filter((s) => !applied.has(s.id));
    if (reviewSuggestions.length) await runReviewQuietly();
    else renderReview();
  });
}

async function runReviewQuietly() {
  const res = await api("POST", "/api/memory/review", { ai: false });
  const ai = reviewSuggestions.filter((s) => s.source === "ai" && (state.memory[s.section] || []).some((x) => x.id === s.item_id));
  reviewSuggestions = [...res.suggestions, ...ai];
  renderReview();
}

$("review-memory").addEventListener("click", runReview);
$("review-run").addEventListener("click", runReview);
$("review-close").addEventListener("click", () => { $("review-panel").hidden = true; });
$("review-apply").addEventListener("click", applyReview);
$("review-select-rules").addEventListener("click", () => {
  $("review-list").querySelectorAll(".review-item.rule input").forEach((b) => { b.checked = true; });
  updateReviewButtons();
});
