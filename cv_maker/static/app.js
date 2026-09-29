"use strict";

const $ = (id) => document.getElementById(id);
let state = null;
let saveTimer = null;
let savingEdits = Promise.resolve();

// ---------- API helpers ----------

async function api(method, url, body) {
  const opts = { method };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({ error: `Request failed (${res.status})` }));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

async function withBusy(text, fn) {
  $("busy-text").textContent = text;
  $("busy").hidden = false;
  try {
    return await fn();
  } catch (err) {
    showNotice(err.message, true);
  } finally {
    $("busy").hidden = true;
  }
}

function showNotice(message, isError = false) {
  const el = $("notice");
  if (!message) { el.hidden = true; return; }
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.hidden = false;
}

// ---------- Rendering ----------

function render(next) {
  state = next;
  const { settings, cv_html, cv_meta, ai_enabled } = state;

  const status = $("ai-status");
  const ai = state.ai_status;
  status.textContent = `AI: ${ai.label}`;
  status.title = ai.message || "";
  status.classList.toggle("off", !ai.ready);
  $("add").disabled = !ai_enabled;

  if (document.activeElement !== $("target")) $("target").value = settings.target || "";
  $("auto").checked = !!settings.auto_rebuild;
  $("page-size-select").value = settings.page_size;
  applyPageSize(settings.page_size);

  const cv = $("cv");
  if (document.activeElement !== cv) cv.innerHTML = cv_html || "";
  cv.hidden = !cv_html;
  $("cv-empty").hidden = !!cv_html;
  $("pdf").disabled = !cv_html;
  setEditStatus(cv_meta.edited ? "edited" : "clean");

  renderList($("advice"), state.advice);
  $("advice-card").hidden = !state.advice.length;

  renderMemory();
  renderHistory();
}

function renderList(ul, items, onClick) {
  ul.replaceChildren(...items.map((text) => {
    const li = document.createElement("li");
    li.textContent = text;
    if (onClick) li.addEventListener("click", () => onClick(text));
    return li;
  }));
}

function showResult({ changes = [], questions = [], notice }) {
  $("result").hidden = !changes.length && !questions.length;
  renderList($("changes"), changes.length ? changes : ["Nothing needed changing."]);
  renderList($("questions"), questions, (q) => {
    const input = $("input");
    input.value = `${q}\n→ `;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  });
  $("questions-wrap").hidden = !questions.length;
  showNotice(notice || "");
}

function setEditStatus(mode) {
  const el = $("edit-status");
  const labels = {
    clean: "Click anywhere on the CV to edit it.",
    saving: "Saving edits…",
    edited: "Edits saved. They'll be replaced on the next rebuild unless you save them to memory.",
  };
  el.textContent = labels[mode];
  el.classList.toggle("dirty", mode !== "clean");
  $("learn").disabled = mode !== "edited" || !state?.ai_enabled;
}

function applyPageSize(size) {
  $("page-size").textContent = `@page { size: ${size === "letter" ? "letter" : "A4"}; }`;
  $("cv").classList.toggle("letter", size === "letter");
}

const SECTION_LABELS = {
  experience: "Experience", education: "Education", projects: "Projects",
  achievements: "Certifications, awards & more",
};

function itemView(section, item) {
  switch (section) {
    case "experience":
      return { title: [item.role, item.organization].filter(Boolean).join(" · "),
               meta: [item.kind !== "work" ? item.kind : "", item.location, dates(item)].filter(Boolean).join(" · "),
               bullets: item.highlights };
    case "education":
      return { title: [item.qualification, item.field].filter(Boolean).join(", ") || item.institution,
               meta: [item.institution, item.grade, dates(item)].filter(Boolean).join(" · "),
               bullets: item.highlights };
    case "projects":
      return { title: item.name, meta: [item.role, dates(item), item.link].filter(Boolean).join(" · "),
               bullets: [item.description, ...item.highlights].filter(Boolean) };
    default:
      return { title: item.title, meta: [item.kind, item.issuer, item.date].filter(Boolean).join(" · "),
               bullets: item.description ? [item.description] : [] };
  }
}

function dates(item) {
  return [item.start, item.end].filter(Boolean).join(" – ");
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderMemory() {
  const m = state.memory;
  const view = $("memory-view");
  const blocks = [];

  const p = m.profile;
  const profileLines = [p.name, p.headline, p.email, p.phone, p.location, ...p.links.map((l) => `${l.label}: ${l.url}`)].filter(Boolean);
  if (profileLines.length || m.summary) {
    const sec = el("div", "mem-section");
    sec.append(el("h3", "", "Profile"));
    profileLines.forEach((line) => sec.append(el("div", "", line)));
    if (m.summary) sec.append(el("p", "meta", m.summary));
    blocks.push(sec);
  }

  for (const [key, label] of Object.entries(SECTION_LABELS)) {
    if (!m[key].length) continue;
    const sec = el("div", "mem-section");
    sec.append(el("h3", "", `${label} (${m[key].length})`));
    m[key].forEach((item, index) => {
      const v = itemView(key, item);
      const row = el("div", "mem-item");
      const body = el("div", "body");
      body.append(el("div", "title", v.title || "(untitled)"));
      if (v.meta) body.append(el("div", "meta", v.meta));
      if (v.bullets.length) {
        const ul = el("ul");
        v.bullets.forEach((b) => ul.append(el("li", "", b)));
        body.append(ul);
      }
      const del = el("button", "del", "×");
      del.title = "Remove from memory";
      del.addEventListener("click", () => removeItem(key, index, v.title));
      row.append(body, del);
      sec.append(row);
    });
    blocks.push(sec);
  }

  const lists = [
    ["Skills", m.skills.map((g) => `${g.category}: ${g.skills.join(", ")}`)],
    ["Languages", m.languages], ["Interests", m.interests],
    ["CV preferences", m.preferences], ["Other notes", m.notes],
  ];
  for (const [label, items] of lists) {
    if (!items.length) continue;
    const sec = el("div", "mem-section");
    sec.append(el("h3", "", label));
    const ul = el("ul");
    items.forEach((i) => ul.append(el("li", "", i)));
    sec.append(ul);
    blocks.push(sec);
  }

  if (!blocks.length) {
    const empty = el("div", "empty");
    empty.append(el("h3", "", "Memory is empty"), el("p", "", "Anything you add on the left is stored here."));
    blocks.push(empty);
  }
  view.replaceChildren(...blocks);
}

function renderHistory() {
  $("undo").disabled = !state.can_undo;
  $("history").replaceChildren(...state.history.map((h) => {
    const li = el("li");
    li.append(el("div", "when", `${new Date(h.at).toLocaleString()} · ${h.source}`));
    if (h.input) li.append(el("div", "input", h.input));
    if (h.changes.length) {
      const ul = el("ul");
      h.changes.forEach((c) => ul.append(el("li", "", c)));
      li.append(ul);
    }
    return li;
  }));
}

// ---------- Actions ----------

function busyText(text) {
  return state.ai_status.local ? `${text} A local model can take a few minutes.` : text;
}

async function addToMemory() {
  const text = $("input").value.trim();
  const files = $("files").files;
  if (!text && !files.length) { $("input").focus(); return; }
  const form = new FormData();
  form.append("text", text);
  for (const f of files) form.append("files", f);
  await savingEdits;
  const rebuilding = state.settings.auto_rebuild && !state.cv_meta.edited;
  await withBusy(busyText(rebuilding ? "Updating memory and rewriting your CV…" : "Updating memory…"), async () => {
    const next = await api("POST", "/api/ingest", form);
    $("input").value = "";
    $("files").value = "";
    $("file-names").textContent = "";
    render(next);
    showResult(next);
  });
}

async function rebuild() {
  await savingEdits;
  if (state.cv_meta.edited &&
      !confirm("Rebuilding replaces your manual edits to the CV. Use 'Save edits to memory' first if you want to keep them. Rebuild anyway?")) return;
  await withBusy(state.ai_enabled ? busyText("Writing the best version of your CV…") : "Building CV…", async () => {
    render(await api("POST", "/api/build", { target: $("target").value }));
    showNotice("");
  });
}

function scheduleEditSave() {
  setEditStatus("saving");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    savingEdits = api("POST", "/api/cv", { html: $("cv").innerHTML })
      .then((next) => { state = next; setEditStatus("edited"); })
      .catch((err) => showNotice(err.message, true));
  }, 800);
}

async function learnFromEdits() {
  await savingEdits;
  await withBusy(busyText("Saving your edits into memory…"), async () => {
    const next = await api("POST", "/api/cv/learn", { text: $("cv").innerText });
    render(next);
    showResult(next);
  });
}

async function saveMemory(memory, busyText = "Saving memory…") {
  return withBusy(busyText, async () => {
    const next = await api("PUT", "/api/memory", memory);
    render(next);
    showNotice(next.notice || "");
    return true;
  });
}

function removeItem(section, index, title) {
  if (!confirm(`Remove "${title || "this item"}" from memory?`)) return;
  const memory = structuredClone(state.memory);
  memory[section].splice(index, 1);
  saveMemory(memory, "Removing…");
}

async function undo() {
  await withBusy("Undoing…", async () => {
    const next = await api("POST", "/api/undo");
    render(next);
    showNotice(next.notice || "");
  });
}

async function saveSettings(patch) {
  try {
    render(await api("POST", "/api/settings", patch));
  } catch (err) {
    showNotice(err.message, true);
  }
}

function downloadPdf() {
  const name = state.memory.profile.name || "My";
  const original = document.title;
  document.title = `${name} CV`; // becomes the suggested PDF file name
  window.print();
  document.title = original;
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  ["cv", "memory", "history"].forEach((t) => { $(`tab-${t}`).hidden = t !== name; });
}

// ---------- AI model picker ----------

let catalog = null;
let catalogKey = "";
let pendingModel = "";   // a picked model that is still downloading
let downloadPoll = null;

async function loadModels() {
  try {
    renderModels(await api("GET", "/api/models"));
  } catch (err) {
    showNotice(err.message, true);
  }
}

function modelValue(backend, model = "") {
  return `${backend}|${model}`;
}

function renderModels(next) {
  catalog = next;
  const sel = $("model-select");
  const key = JSON.stringify([next.local, next.claude_available, next.choice, pendingModel]);
  if (key !== catalogKey) {  // rebuilding the list closes it if open, so only do it on change
    catalogKey = key;
    const free = document.createElement("optgroup");
    free.label = "Free, runs on this computer";
    for (const m of next.local) {
      const opt = new Option(`${m.name}${m.size ? ` (${m.size})` : ""}${m.installed ? "" : " · not downloaded"}`,
                             modelValue("ollama", m.name));
      free.append(opt);
    }
    const paid = document.createElement("optgroup");
    paid.label = "Paid, best quality";
    const claude = new Option(next.claude_available ? "Claude" : "Claude (needs an API key)", modelValue("claude"));
    claude.disabled = !next.claude_available;
    paid.append(claude);
    const none = new Option("No AI (plain layout)", modelValue("none"));
    sel.replaceChildren(free, paid, none);
    sel.value = pendingModel
      ? modelValue("ollama", pendingModel)
      : modelValue(next.choice.backend, next.choice.backend === "ollama" ? next.choice.model : "");
  }
  sel.disabled = next.pinned;
  updateModelNote();
}

function selected() {
  const [backend, model] = $("model-select").value.split("|");
  const local = backend === "ollama" ? catalog.local.find((m) => m.name === model) || { name: model, installed: false } : null;
  return { backend, model, local };
}

function updateModelNote() {
  const { backend, local } = selected();
  const note = $("model-note");
  let text = "";
  let cls = "";
  if (backend === "claude") {
    [text, cls] = ["Fast and the best writing. Costs a few cents per update.", "ok"];
  } else if (backend === "none") {
    text = "Your CV is laid out straight from memory, without AI wording.";
  } else if (!catalog.ollama_running) {
    [text, cls] = ["Ollama isn't running. Open the Ollama app and this box will update.", "warn"];
  } else if (local.installed) {
    [text, cls] = [local.note || "Ready.", "ok"];
  } else {
    text = local.note || "";
  }
  note.textContent = text;
  note.className = `hint model-note ${cls}`;

  const needsDownload = backend === "ollama" && catalog.ollama_running && !local.installed;
  $("model-download").hidden = !needsDownload;
  if (!needsDownload) return;
  const dl = catalog.downloads[local.name];
  const downloading = dl?.state === "downloading";
  const pct = dl?.total ? Math.round((100 * dl.completed) / dl.total) : 0;
  $("download-btn").hidden = downloading;
  $("download-btn").textContent = `Download ${local.name}${local.size ? ` (${local.size})` : ""}`;
  $("download-progress").hidden = !downloading;
  $("download-progress").firstElementChild.style.width = `${pct}%`;
  $("download-status").textContent = !dl
    ? "Downloads once. After that it works offline."
    : downloading ? `Downloading… ${pct ? `${pct}%` : dl.status}` : dl.status;
}

async function onModelChange() {
  const { backend, model, local } = selected();
  if (local && !local.installed) {
    pendingModel = model;  // switch to it once it's downloaded
    updateModelNote();
    return;
  }
  pendingModel = "";
  try {
    render(await api("POST", "/api/models/choose", { backend, model }));
    showNotice("");
  } catch (err) {
    showNotice(err.message, true);
  }
  loadModels();
}

async function downloadModel() {
  const { local } = selected();
  pendingModel = local.name;
  try {
    renderModels(await api("POST", "/api/models/download", { model: local.name }));
  } catch (err) {
    showNotice(err.message, true);
    return;
  }
  if (downloadPoll) return;
  downloadPoll = setInterval(async () => {
    const next = await api("GET", "/api/models").catch(() => null);
    if (!next) return;
    renderModels(next);
    if (Object.values(next.downloads).some((d) => d.state === "downloading")) return;
    clearInterval(downloadPoll);
    downloadPoll = null;
    const { local: now } = selected();
    if (now?.installed && now.name === pendingModel) onModelChange();
  }, 1000);
}

// ---------- Wiring ----------

document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
$("add").addEventListener("click", addToMemory);
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) addToMemory();
});
$("files").addEventListener("change", () => {
  $("file-names").textContent = [...$("files").files].map((f) => f.name).join(", ");
});
$("rebuild").addEventListener("click", rebuild);
$("auto").addEventListener("change", (e) => saveSettings({ auto_rebuild: e.target.checked }));
$("target").addEventListener("change", (e) => saveSettings({ target: e.target.value }));
$("page-size-select").addEventListener("change", (e) => saveSettings({ page_size: e.target.value }));
$("cv").addEventListener("input", scheduleEditSave);
$("cv").addEventListener("paste", (e) => {
  // Paste as plain text so formatting from other apps doesn't leak into the CV.
  e.preventDefault();
  document.execCommand("insertText", false, e.clipboardData.getData("text/plain"));
});
$("learn").addEventListener("click", learnFromEdits);
$("pdf").addEventListener("click", downloadPdf);
$("undo").addEventListener("click", undo);

$("toggle-json").addEventListener("click", () => {
  const open = $("json-wrap").hidden;
  $("json-wrap").hidden = !open;
  $("memory-view").hidden = open;
  $("toggle-json").textContent = open ? "Back to overview" : "Edit as JSON";
  if (open) $("json").value = JSON.stringify(state.memory, null, 2);
});
$("json-cancel").addEventListener("click", () => $("toggle-json").click());
$("json-save").addEventListener("click", async () => {
  let memory;
  try {
    memory = JSON.parse($("json").value);
  } catch (err) {
    showNotice(`That isn't valid JSON: ${err.message}`, true);
    return;
  }
  if (await saveMemory(memory)) $("toggle-json").click();
});

$("model-select").addEventListener("change", onModelChange);
$("download-btn").addEventListener("click", downloadModel);
window.addEventListener("focus", () => { if (!downloadPoll) loadModels(); });

api("GET", "/api/state").then(render).catch((err) => showNotice(err.message, true));
loadModels();
