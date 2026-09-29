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

  if (document.activeElement !== $("target")) $("target").value = state.target || "";
  $("aim-title").textContent = state.active.id === "general" ? "Aim the CV" : `Job ad for ${state.active.name}`;
  $("auto").checked = !!settings.auto_rebuild;
  $("page-size-select").value = settings.page_size;
  applyPageSize(settings.page_size);

  const cv = $("cv");
  if (document.activeElement !== cv) cv.innerHTML = cv_html || "";
  cv.hidden = !cv_html;
  $("cv-empty").hidden = !!cv_html;
  $("pdf").disabled = !cv_html;
  $("docx").disabled = !cv_html;
  setEditStatus(cv_meta.edited ? "edited" : "clean");

  renderList($("advice"), state.advice);
  $("advice-card").hidden = !state.advice.length;

  applyDesign();
  layoutPages();
  runChecks();
  renderSections();
  renderVersions();
  renderApplications();
  if (typeof renderLetter === "function") renderLetter();
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
  const page = size === "letter" ? "letter" : "A4";
  // Browsers print their own header and footer (date, page address) in the page margin.
  // Where the browser can repeat padding on every printed page, use no page margin at all,
  // so there's nowhere for that header and footer to go.
  $("page-size").textContent = CSS.supports("box-decoration-break", "clone")
    ? `@page { size: ${page}; margin: 0; }
       @media print { .paper, .paper.letter { padding: 13mm 14mm !important; box-decoration-break: clone; } }`
    : `@page { size: ${page}; margin: 13mm 14mm; }`;
  $("cv").classList.toggle("letter", size === "letter");
}

const SECTION_LABELS = {
  experience: "Experience", education: "Education", projects: "Projects",
  achievements: "Publications, certifications & awards",
};
const ADD_LABELS = { experience: "job or role", education: "school or degree", projects: "project", achievements: "publication, award…" };

// [field, label, type, options/placeholder]. type: text (default), select, textarea, lines, csv
const FIELDS = {
  experience: [
    ["role", "Job title"], ["organization", "Organisation (company, lab, department)"],
    ["kind", "Type", "select", ["work", "internship", "volunteering", "freelance", "other"]],
    ["location", "Location"], ["start", "Start", "text", "e.g. 2024-07"], ["end", "End", "text", "e.g. 2025-06 or Present"],
    ["description", "Short description", "textarea"],
    ["highlights", "What you did and achieved (one per line)", "lines"],
    ["skills", "Skills and tools used (comma separated)", "csv"],
  ],
  education: [
    ["qualification", "Qualification", "text", "e.g. BSc"], ["field", "Subject", "text", "e.g. Data Theory"],
    ["institution", "Institution"], ["location", "Location"],
    ["start", "Start", "text", "e.g. 2021-09"], ["end", "End", "text", "e.g. 2025-06"],
    ["grade", "Grade or GPA", "text", "e.g. 3.6/4.0"],
    ["highlights", "Details (one per line): coursework, honours…", "lines"],
  ],
  projects: [
    ["name", "Project name"], ["role", "Your role (optional)"], ["link", "Link (optional)"],
    ["start", "Start", "text", "e.g. 2025-01"], ["end", "End", "text", "e.g. 2025-06 or Present"],
    ["description", "Short description", "textarea"],
    ["highlights", "What you did and achieved (one per line)", "lines"],
    ["skills", "Skills and tools used (comma separated)", "csv"],
  ],
  achievements: [
    ["title", "Title"], ["kind", "Type", "select", ["publication", "talk", "certification", "award", "other"]],
    ["issuer", "Issuer, journal or venue"], ["date", "Date", "text", "e.g. 2025-03"],
    ["description", "Description", "textarea"],
  ],
};
const PROFILE_FIELDS = [
  ["name", "Full name"], ["headline", "Headline", "text", "e.g. Data Science Graduate"],
  ["email", "Email"], ["phone", "Phone"], ["location", "Location"],
  ["links", "Links (one per line, e.g. GitHub: github.com/you)", "lines"],
  ["summary", "Your own summary (optional)", "textarea"],
];
const LIST_SECTIONS = [
  ["skills", "Skills", "One group per line, e.g. Programming: Python, R, SQL"],
  ["languages", "Languages", "One per line, e.g. Cantonese (native)"],
  ["interests", "Interests", "One per line"],
  ["preferences", "CV preferences", "One per line, e.g. Use UK spelling"],
  ["notes", "Other notes", "One per line, e.g. Targeting data science roles"],
];

let editing = null;  // {section, index} | {section: "profile"} | {section: "list:<name>"}

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

function button(text, className, onClick, title) {
  const b = el("button", className, text);
  b.type = "button";
  if (title) b.title = title;
  b.addEventListener("click", onClick);
  return b;
}

// ---- form helpers ----

function fieldInput([name, label, type = "text", extra], value) {
  const wrap = el("label", "field");
  wrap.append(el("span", "field-label", label));
  let input;
  if (type === "select") {
    input = el("select");
    const options = extra.includes(value) || !value ? extra : [value, ...extra];
    options.forEach((o) => input.append(new Option(o, o)));
    input.value = value || extra[0];
  } else if (type === "textarea" || type === "lines") {
    input = el("textarea");
    input.rows = type === "lines" ? Math.max(3, (value || []).length + 1) : 2;
    input.value = type === "lines" ? (value || []).join("\n") : value || "";
  } else {
    input = el("input");
    input.type = "text";
    input.value = type === "csv" ? (value || []).join(", ") : value || "";
    if (extra) input.placeholder = extra;
  }
  input.name = name;
  input.dataset.type = type;
  wrap.append(input);
  return wrap;
}

function readForm(form) {
  const out = {};
  form.querySelectorAll("[name]").forEach((input) => {
    const v = input.value;
    switch (input.dataset.type) {
      case "lines": out[input.name] = v.split("\n").map((s) => s.trim()).filter(Boolean); break;
      case "csv": out[input.name] = v.split(",").map((s) => s.trim()).filter(Boolean); break;
      default: out[input.name] = v.trim();
    }
  });
  return out;
}

function formShell(onSave, extraButtons = []) {
  const form = el("form", "mem-form");
  const actions = el("div", "row end");
  actions.append(...extraButtons, button("Cancel", "", () => { editing = null; renderMemory(); }));
  const save = el("button", "primary", "Save");
  save.type = "submit";
  actions.append(save);
  form.addEventListener("submit", (e) => { e.preventDefault(); onSave(form); });
  return [form, actions];
}

// Converting between experience and projects when an entry is in the wrong section.
function moveItem(item, from, to) {
  const shared = { id: item.id, start: item.start, end: item.end, description: item.description,
                   highlights: item.highlights, skills: item.skills || [] };
  if (from === "experience" && to === "projects") {
    return { ...shared, name: item.role || item.organization, role: "", link: "" };
  }
  if (from === "projects" && to === "experience") {
    return { ...shared, role: item.role || item.name, organization: item.role ? item.name : "",
             kind: "other", location: "" };
  }
  return item;
}

function itemForm(section, index) {
  const isNew = index < 0;
  const item = isNew ? {} : state.memory[section][index];
  const canMove = section === "experience" || section === "projects";
  const moveSelect = el("select");
  if (canMove) {
    moveSelect.append(new Option(`Keep in ${SECTION_LABELS[section]}`, section));
    const other = section === "experience" ? "projects" : "experience";
    moveSelect.append(new Option(`Move to ${SECTION_LABELS[other]}`, other));
  }
  const [form, actions] = formShell((f) => {
    const memory = structuredClone(state.memory);
    let updated = { ...item, ...readForm(f) };
    const target = canMove ? moveSelect.value : section;
    if (target !== section) updated = moveItem(updated, section, target);
    if (isNew) memory[section].push(updated);
    else if (target === section) memory[section][index] = updated;
    else {
      memory[section].splice(index, 1);
      memory[target].push(updated);
    }
    editing = null;
    saveMemory(memory, "Saving…");
  }, isNew ? [] : [button("Delete", "danger", () => removeItem(section, index, itemView(section, item).title))]);
  FIELDS[section].forEach((spec) => form.append(fieldInput(spec, item[spec[0]])));
  if (canMove && !isNew) {
    const wrap = el("label", "field");
    wrap.append(el("span", "field-label", "Section"), moveSelect);
    form.append(wrap);
  }
  form.append(actions);
  return form;
}

function profileForm() {
  const m = state.memory;
  const values = { ...m.profile, links: m.profile.links.map((l) => (l.label ? `${l.label}: ${l.url}` : l.url)),
                   summary: m.summary };
  const [form, actions] = formShell((f) => {
    const data = readForm(f);
    const memory = structuredClone(state.memory);
    const links = data.links.map((line) => {
      const match = line.match(/^([^:]{1,30}):\s*(\S.*)$/);
      return match && !/^https?$/i.test(match[1]) ? { label: match[1].trim(), url: match[2].trim() } : { label: "", url: line };
    });
    memory.profile = { ...memory.profile, ...data, links };
    delete memory.profile.summary;
    memory.summary = data.summary;
    editing = null;
    saveMemory(memory, "Saving…");
  });
  PROFILE_FIELDS.forEach((spec) => form.append(fieldInput(spec, values[spec[0]])));
  form.append(actions);
  return form;
}

function listForm(name, hint) {
  const m = state.memory;
  const lines = name === "skills" ? m.skills.map((g) => (g.category ? `${g.category}: ${g.skills.join(", ")}` : g.skills.join(", "))) : m[name];
  const [form, actions] = formShell((f) => {
    const values = readForm(f).lines;
    const memory = structuredClone(state.memory);
    memory[name] = name === "skills"
      ? values.map((line) => {
          const [cat, rest] = line.includes(":") ? line.split(/:(.*)/s) : ["", line];
          return { category: cat.trim(), skills: rest.split(",").map((s) => s.trim()).filter(Boolean) };
        })
      : values;
    editing = null;
    saveMemory(memory, "Saving…");
  });
  form.append(fieldInput(["lines", hint, "lines"], lines), actions);
  return form;
}

function sectionBlock(title, onEdit, editLabel = "Edit") {
  const sec = el("div", "mem-section");
  const head = el("div", "mem-head");
  head.append(el("h3", "", title));
  if (onEdit) head.append(button(editLabel, "small", onEdit));
  sec.append(head);
  return sec;
}

function renderMemory() {
  const m = state.memory;
  const view = $("memory-view");
  const blocks = [];
  const open = (e) => { editing = e; renderMemory(); };

  const p = m.profile;
  const profile = sectionBlock("Profile", () => open({ section: "profile" }));
  if (editing?.section === "profile") profile.append(profileForm());
  else {
    const lines = [p.name, p.headline, p.email, p.phone, p.location, ...p.links.map((l) => `${l.label ? `${l.label}: ` : ""}${l.url}`)].filter(Boolean);
    lines.forEach((line) => profile.append(el("div", "", line)));
    if (m.summary) profile.append(el("p", "meta", m.summary));
    if (!lines.length && !m.summary) profile.append(el("div", "meta", "Name and contact details go here."));
  }
  blocks.push(profile);

  for (const [key, label] of Object.entries(SECTION_LABELS)) {
    const sec = sectionBlock(`${label} (${m[key].length})`, () => open({ section: key, index: -1 }), `+ Add ${ADD_LABELS[key]}`);
    m[key].forEach((item, index) => {
      if (editing?.section === key && editing.index === index) {
        sec.append(itemForm(key, index));
        return;
      }
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
      const tools = el("div", "item-tools");
      tools.append(button("Edit", "small", () => open({ section: key, index })),
                   button("×", "del", () => removeItem(key, index, v.title), "Remove from memory"));
      row.append(body, tools);
      sec.append(row);
    });
    if (editing?.section === key && editing.index === -1) sec.append(itemForm(key, -1));
    blocks.push(sec);
  }

  for (const [name, label, hint] of LIST_SECTIONS) {
    const items = name === "skills" ? m.skills.map((g) => (g.category ? `${g.category}: ${g.skills.join(", ")}` : g.skills.join(", "))) : m[name];
    const sec = sectionBlock(label, () => open({ section: `list:${name}` }));
    if (editing?.section === `list:${name}`) sec.append(listForm(name, hint));
    else if (items.length) {
      const ul = el("ul");
      items.forEach((i) => ul.append(el("li", "", i)));
      sec.append(ul);
    } else sec.append(el("div", "meta", "Nothing yet."));
    blocks.push(sec);
  }
  view.replaceChildren(...blocks);
  view.querySelector(".mem-form input, .mem-form textarea")?.focus();
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
    const next = await api("PUT", "/api/memory?rebuild=0", memory);
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

async function downloadFile(url, busyMessage) {
  await savingEdits;
  return withBusy(busyMessage, async () => {
    const res = await fetch(url);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      const err = new Error(data.error || `Download failed (${res.status})`);
      err.status = res.status;
      throw err;
    }
    const match = /filename\*=UTF-8''([^;]+)/.exec(res.headers.get("Content-Disposition") || "");
    const name = match ? decodeURIComponent(match[1]) : url.split("/").pop();
    const link = el("a");
    link.href = URL.createObjectURL(await res.blob());
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 10000);
    return true;
  });
}

function printFallback(kind) {
  const name = state.memory.profile.name || "My";
  const original = document.title;
  document.title = `${name} ${kind}`; // becomes the suggested PDF file name
  window.print();
  document.title = original;
}

async function downloadPdf() {
  const scale = parseFloat(getComputedStyle($("cv")).getPropertyValue("--cv-scale")) || 1;
  const ok = await downloadFile(`/api/export/cv.pdf?scale=${scale}`, "Making your PDF…");
  if (!ok && $("notice").textContent.includes("No Chrome")) {
    showNotice("No Chrome, Edge or Brave browser was found, so the print window opened instead. Choose 'Save as PDF'.");
    printFallback("CV");
  }
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  ["cv", "letter", "applications", "memory", "history"].forEach((t) => { if ($(`tab-${t}`)) $(`tab-${t}`).hidden = t !== name; });
}

// ---------- Design, page fitting and CV check ----------

const ACCENTS = ["#1f4e79", "#0f6e6e", "#2f6b3a", "#8a1c2b", "#4b3b8f", "#333a44"];
const PAGE_MM = { A4: 297, letter: 279.4 };
const PAD_MM = 13;          // top/bottom padding of each printed page
const MIN_SCALE = 0.82;     // smallest "fit to one page" will go (about 8.6pt text)
const FIT_SLACK_MM = 8;     // printing lays text out slightly differently from the screen; leave room
let pxPerMm = 0;
let layoutTimer = null;
let lastPages = 1;
let fitFailed = false;

function mm(n) {
  if (!pxPerMm) {
    const probe = el("div");
    probe.style.cssText = "position:absolute;visibility:hidden;width:100mm";
    document.body.append(probe);
    pxPerMm = probe.getBoundingClientRect().width / 100;
    probe.remove();
  }
  return n * pxPerMm;
}

function applyDesign() {
  const { template, accent } = state.settings;
  const cv = $("cv");
  cv.classList.remove("t-classic", "t-modern", "t-minimal");
  cv.classList.add(`t-${template}`);
  if (template === "modern") cv.style.setProperty("--cv-accent", accent);
  else cv.style.removeProperty("--cv-accent");
  $("design-bar").hidden = !state.cv_html;
  document.querySelectorAll("#template-picker button").forEach((b) => b.classList.toggle("active", b.dataset.template === template));
  $("accent-picker").hidden = template !== "modern";
  if (!$("accent-picker").children.length) {
    for (const color of ACCENTS) {
      const b = button("", "", () => saveSettings({ accent: color }), "Accent colour");
      b.style.background = color;
      b.dataset.color = color;
      $("accent-picker").append(b);
    }
  }
  [...$("accent-picker").children].forEach((b) => b.classList.toggle("active", b.dataset.color === accent));
  $("fit").checked = !!state.settings.fit_one_page;
}

function contentHeight(cv) {
  const top = cv.getBoundingClientRect().top + parseFloat(getComputedStyle(cv).paddingTop);
  let bottom = top;
  for (const child of cv.children) {
    if (child.hidden) continue;
    bottom = Math.max(bottom, child.getBoundingClientRect().bottom + parseFloat(getComputedStyle(child).marginBottom || 0));
  }
  return bottom - top;
}

function layoutPages() {
  const cv = $("cv");
  const guides = $("page-guides");
  if (cv.hidden || !state?.cv_html) { guides.replaceChildren(); return; }
  const usable = mm(PAGE_MM[state.settings.page_size === "letter" ? "letter" : "A4"] - 2 * PAD_MM);

  let scale = 1;
  cv.style.setProperty("--cv-scale", "1");
  fitFailed = false;
  const target = usable - mm(FIT_SLACK_MM);
  if (state.settings.fit_one_page && contentHeight(cv) > target) {
    let lo = MIN_SCALE, hi = 1;
    cv.style.setProperty("--cv-scale", String(lo));
    if (contentHeight(cv) > target) {
      scale = lo;
      fitFailed = true;
    } else {
      for (let i = 0; i < 7; i++) {
        const mid = (lo + hi) / 2;
        cv.style.setProperty("--cv-scale", String(mid));
        if (contentHeight(cv) <= target) lo = mid; else hi = mid;
      }
      scale = lo;
    }
    cv.style.setProperty("--cv-scale", scale.toFixed(3));
  }

  const height = contentHeight(cv);
  lastPages = Math.max(1, Math.ceil((height - 1) / usable));
  const top = parseFloat(getComputedStyle(cv).paddingTop);
  guides.replaceChildren(...Array.from({ length: lastPages - 1 }, (_, i) => {
    const g = el("div", "page-guide");
    g.style.top = `${top + usable * (i + 1)}px`;
    g.append(el("span", "", `Page ${i + 2} starts about here`));
    return g;
  }));

  const count = $("page-count");
  const size = scale < 1 ? ` · text at ${Math.round(scale * 100)}%` : "";
  count.textContent = fitFailed
    ? "Still over one page at the smallest size. Hide a section or shorten some bullets."
    : `${lastPages} page${lastPages > 1 ? "s" : ""}${size}`;
  count.classList.toggle("warn", fitFailed || lastPages > 2);
}

function scheduleLayout() {
  clearTimeout(layoutTimer);
  layoutTimer = setTimeout(() => { layoutPages(); runChecks(); }, 300);
}

// ---- CV check ----

const WEAK_START = /^(responsible for|helped|assisted|worked on|involved in|participated in|duties included|tasked with|in charge of|handled)\b/i;
const STOP = new Set(`a an the and or but if of to in on for with at by from as is are was were be been being this that these
those it its you your we our they their he she his her will would can could should may might must not no yes all any some such
than then there here who whom which what when where why how also etc per via into onto over under within without about across
after before during include includes including required requirements require requires preferred qualifications qualification
responsibilities responsibility role roles position job jobs candidate candidates team teams work working works experience
experienced years year ability able strong excellent good great skills skill knowledge understanding opportunity opportunities
company business environment plus using use used new well related relevant least minimum degree bachelor bachelors master
masters phd field equivalent join looking seeking help make based highly other others more most one two three four five
we're you'll you're it's our us across both each every just like need needs needed want wants within day days time full part
apply application applications salary benefits location remote hybrid office offer offers provide provides support ensure
across key new develop development developing build building create creating manage managing lead leading drive driving
deliver delivering deliverables stakeholders proven track record demonstrated excellent communication communicate
written verbal detail oriented self motivated fast paced dynamic passionate problem solving solve solving
results communicating collaborate collaborating collaboration looking ideal ideally familiarity familiar exposure`.split(/\s+/));

function jobKeywords(text) {
  const scores = new Map();
  const display = new Map();
  for (const raw of text.match(/[A-Za-z][A-Za-z0-9+#.\-]*[A-Za-z0-9+#]|[A-Za-z]/g) || []) {
    const word = raw.replace(/\.$/, "");
    const key = word.toLowerCase();
    const acronym = word === word.toUpperCase() && /[A-Z]/.test(word);
    if (STOP.has(key) || (key.length < 3 && !acronym)) continue;
    const bonus = /[A-Z+#]/.test(word.slice(1)) || acronym || /^[A-Z]/.test(word) ? 1 : 0;
    scores.set(key, (scores.get(key) || 0) + 1 + bonus);
    if (!display.has(key) || acronym) display.set(key, word);
  }
  return [...scores.entries()].sort((a, b) => b[1] - a[1]).slice(0, 20).map(([key]) => ({ key, label: display.get(key) }));
}

function hasWord(haystack, key) {
  if (/[^a-z0-9]/.test(key)) return haystack.includes(key);
  return new RegExp(`(^|[^a-z0-9])${key}([^a-z0-9]|$)`).test(haystack);
}

function snippetButton(li) {
  const text = li.textContent.trim();
  return button(`“${text.length > 70 ? `${text.slice(0, 70)}…` : text}”`, "snip", () => {
    li.scrollIntoView({ block: "center", behavior: "smooth" });
    li.classList.add("flash");
    setTimeout(() => li.classList.remove("flash"), 1600);
  });
}

function runChecks() {
  const panel = $("check-panel");
  if (!state?.cv_html) { panel.hidden = true; return; }
  panel.hidden = false;
  const cv = $("cv");
  const visible = [...cv.querySelectorAll("section.cv-section")].filter((s) => !s.hidden);
  // Achievement bullets (jobs, projects); education details like coursework don't need numbers.
  const bullets = visible.filter((s) => !/education/.test(s.dataset.section || ""))
    .flatMap((s) => [...s.querySelectorAll(".cv-entry li")]);
  const checks = [];
  const add = (level, text, detail = "", extra = null) => checks.push({ level, text, detail, extra });

  if (fitFailed) add("warn", "Doesn't fit on one page", "Hide a section in the Sections box or shorten some bullets.");
  else if (lastPages > 2) add("warn", `${lastPages} pages is long`, "Recruiters skim. Aim for one page as a student or graduate, two at most.");
  else if (lastPages === 2) add("info", "Two pages", "Fine with several years of experience. As a student or graduate, try 'Fit to one page'.");
  else add("ok", "Fits on one page");

  const gaps = cv.querySelectorAll("mark.placeholder");
  if (gaps.length) add("warn", `${gaps.length} unfilled gap${gaps.length > 1 ? "s" : ""} like ${gaps[0].textContent}`,
                       "Replace them with real details before sending.",
                       [...new Set([...gaps].map((g) => g.closest("li") || g.parentElement))].slice(0, 5));

  const noNumbers = bullets.filter((li) => !/\d/.test(li.textContent));
  if (bullets.length && noNumbers.length / bullets.length > 0.5) {
    add("warn", `${noNumbers.length} of ${bullets.length} bullets have no numbers`,
        "Numbers make impact concrete: how many, how much, how fast, what percentage.", noNumbers.slice(0, 5));
  } else if (bullets.length) add("ok", "Most bullets include numbers");

  const weak = bullets.filter((li) => WEAK_START.test(li.textContent.trim()));
  if (weak.length) add("warn", `${weak.length} bullet${weak.length > 1 ? "s" : ""} start weakly`,
                       "Start with what you did: Built, Led, Designed, Automated, Analysed…", weak.slice(0, 5));

  const long = bullets.filter((li) => li.textContent.trim().length > 220);
  if (long.length) add("info", `${long.length} bullet${long.length > 1 ? "s are" : " is"} very long`,
                       "Keep bullets to one or two lines so they're easy to skim.", long.slice(0, 5));

  const p = state.memory.profile;
  const missing = [!p.email && "email", !p.phone && "phone", !p.links.length && "a LinkedIn or GitHub link"].filter(Boolean);
  if (missing.length) add("info", `Contact details missing: ${missing.join(", ")}`, "Add them with Edit on Profile in the Memory tab.");
  else add("ok", "Contact details complete");

  const target = (state.target || "").trim();
  if (target.split(/\s+/).length >= 15) {
    const words = jobKeywords(target);
    const text = cv.innerText.toLowerCase();
    const have = words.filter((w) => hasWord(text, w.key));
    const lacking = words.filter((w) => !hasWord(text, w.key));
    add(lacking.length > words.length / 2 ? "warn" : "info",
        `Job ad keywords on your CV: ${have.length} of ${words.length}`,
        "Automatic screening looks for these words. Add missing ones only where they're true for you.",
        { have, lacking });
  } else {
    add("info", "Paste a job ad into 'Aim the CV' to see which of its keywords your CV is missing");
  }

  const issues = checks.filter((c) => c.level === "warn").length;
  $("check-summary").innerHTML = "";
  $("check-summary").append("CV check ", el("span", "count", issues ? `· ${issues} thing${issues > 1 ? "s" : ""} to fix` : "· looking good"));
  $("check-list").replaceChildren(...checks.map((c) => {
    const row = el("div", `check-item ${c.level}`);
    const body = el("div");
    body.append(el("div", "", c.text));
    if (c.detail) body.append(el("div", "detail", c.detail));
    if (Array.isArray(c.extra) && c.extra.length) {
      const snips = el("div", "snips");
      c.extra.forEach((li) => snips.append(snippetButton(li)));
      body.append(snips);
    } else if (c.extra?.lacking) {
      const chips = el("div", "chips");
      c.extra.lacking.forEach((w) => chips.append(el("span", "chip", w.label)));
      c.extra.have.forEach((w) => chips.append(el("span", "chip have", `✓ ${w.label}`)));
      body.append(chips);
    }
    row.append(el("span", "icon", { ok: "✓", warn: "!", info: "i" }[c.level]), body);
    return row;
  }));
}

// ---------- Versions and applications ----------

const NEW_VERSION = "__new__";

function renderVersions() {
  const sel = $("version-select");
  const options = [new Option("General CV", "general")];
  for (const v of state.versions) options.push(new Option(`${v.name} · ${v.status}`, v.id));
  options.push(new Option("＋ New CV for a job…", NEW_VERSION));
  sel.replaceChildren(...options);
  sel.value = state.active.id;
}

async function openVersion(id, tab = "cv") {
  await savingEdits;
  try {
    render(await api("POST", "/api/versions/active", { id }));
    showNotice("");
    switchTab(tab);
  } catch (err) {
    showNotice(err.message, true);
  }
}

async function saveTarget(target) {
  try {
    render(await api("PATCH", `/api/versions/${state.active.id}`, { target }));
  } catch (err) {
    showNotice(err.message, true);
  }
}

function showAppForm(show) {
  $("app-form").hidden = !show;
  if (show) {
    $("app-form").reset();
    $("app-form").elements.company.focus();
  }
}

async function createApplication(e) {
  e.preventDefault();
  const f = $("app-form").elements;
  const body = { company: f.company.value, role: f.role.value, link: f.link.value, target: f.target.value };
  await withBusy(busyText("Creating a CV tailored to this job…"), async () => {
    const next = await api("POST", "/api/versions", body);
    showAppForm(false);
    render(next);
    showNotice(next.notice || "");
    switchTab("cv");
  });
}

async function updateApplication(id, fields) {
  try {
    render(await api("PATCH", `/api/versions/${id}`, fields));
  } catch (err) {
    showNotice(err.message, true);
  }
}

async function deleteApplication(v) {
  if (!confirm(`Delete the application "${v.name}" and its CV? This can't be undone.`)) return;
  try {
    render(await api("DELETE", `/api/versions/${v.id}`));
  } catch (err) {
    showNotice(err.message, true);
  }
}

function renderApplications() {
  const list = $("app-list");
  const counts = {};
  state.versions.forEach((v) => { counts[v.status] = (counts[v.status] || 0) + 1; });
  const summary = $("app-summary");
  if (state.versions.length) {
    summary.replaceChildren(el("span", "app-stats", ""));
    const stats = summary.firstChild;
    stats.append(el("span", "", `${state.versions.length} application${state.versions.length > 1 ? "s" : ""}:`));
    state.statuses.filter((s) => counts[s]).forEach((s) => stats.append(el("span", `status ${s}`, `${counts[s]} ${s.toLowerCase()}`)));
  } else {
    summary.textContent = "Each application gets its own CV, tailored to the job ad, so your general CV stays as it is.";
  }
  if (!state.versions.length) {
    const empty = el("div", "empty");
    empty.append(el("h3", "", "No applications yet"),
                 el("p", "", "Click 'New application', paste the job ad, and you'll get a CV tailored to it. Track its status here."));
    list.replaceChildren(empty);
    return;
  }
  list.replaceChildren(...state.versions.map((v) => {
    const card = el("div", `app-card${v.id === state.active.id ? " active" : ""}`);
    const head = el("div");
    const name = el("div", "name", v.name);
    name.append(el("span", `status ${v.status}`, v.status));
    head.append(name);
    const meta = el("div", "meta");
    meta.append(`Created ${new Date(v.created).toLocaleDateString()}`);
    if (v.link) {
      meta.append(" · ");
      const a = el("a", "", "Job ad");
      a.href = /^https?:/i.test(v.link) ? v.link : `https://${v.link}`;
      a.target = "_blank";
      a.rel = "noopener";
      meta.append(a);
    }
    head.append(meta);

    const actions = el("div", "actions");
    actions.append(button("Open CV", "small primary", () => openVersion(v.id)),
                   button("Cover letter", "small", () => openVersion(v.id, "letter")),
                   button("Delete", "small danger", () => deleteApplication(v)));

    const fields = el("div", "fields");
    const status = el("select");
    state.statuses.forEach((s) => status.append(new Option(s, s)));
    status.value = v.status;
    status.addEventListener("change", () => {
      const patch = { status: status.value };
      if (status.value === "Applied" && !v.applied) patch.applied = new Date().toISOString().slice(0, 10);
      updateApplication(v.id, patch);
    });
    const applied = el("input");
    applied.type = "date";
    applied.value = v.applied || "";
    applied.addEventListener("change", () => updateApplication(v.id, { applied: applied.value }));
    const notes = el("textarea");
    notes.rows = 1;
    notes.placeholder = "Notes: contact, interview dates, follow-ups…";
    notes.value = v.notes || "";
    notes.addEventListener("change", () => updateApplication(v.id, { notes: notes.value }));
    const wrap = (label, input) => { const l = el("label", "field"); l.append(el("span", "field-label", label), input); return l; };
    fields.append(wrap("Status", status), wrap("Applied on", applied), wrap("Notes", notes));
    card.append(head, actions, fields);
    return card;
  }));
}

// ---------- Section arranger ----------

let dragKey = null;

function renderSections() {
  const rows = state.sections || [];
  $("sections-card").hidden = !rows.length;
  const movable = rows.filter((r) => !r.fixed);
  $("section-list").replaceChildren(...rows.map((row) => {
    const li = el("li");
    li.dataset.key = row.key;
    li.classList.toggle("is-hidden", row.hidden);
    const check = el("input");
    check.type = "checkbox";
    check.checked = !row.hidden;
    check.title = row.hidden ? "Show this section" : "Hide this section";
    check.addEventListener("change", () => saveLayout(movable.map((r) => r.key), toggled(row.key, !check.checked)));
    li.append(el("span", "grip", row.fixed ? "" : "⋮⋮"), check, el("span", "name", row.heading));
    if (row.fixed) {
      li.title = "The summary always stays at the top.";
      return li;
    }
    const i = movable.indexOf(row);
    const up = button("▲", "move", () => moveTo(row.key, i - 1), "Move up");
    const down = button("▼", "move", () => moveTo(row.key, i + 1), "Move down");
    up.disabled = i === 0;
    down.disabled = i === movable.length - 1;
    li.append(up, down);

    li.draggable = true;
    li.addEventListener("dragstart", (e) => {
      dragKey = row.key;
      li.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", row.key);
    });
    li.addEventListener("dragend", () => {
      dragKey = null;
      document.querySelectorAll(".section-list li").forEach((n) => n.classList.remove("dragging", "drop-before", "drop-after"));
    });
    li.addEventListener("dragover", (e) => {
      if (!dragKey || dragKey === row.key) return;
      e.preventDefault();
      const after = e.clientY > li.getBoundingClientRect().top + li.offsetHeight / 2;
      li.classList.toggle("drop-before", !after);
      li.classList.toggle("drop-after", after);
    });
    li.addEventListener("dragleave", () => li.classList.remove("drop-before", "drop-after"));
    li.addEventListener("drop", (e) => {
      e.preventDefault();
      const after = li.classList.contains("drop-after");
      li.classList.remove("drop-before", "drop-after");
      if (!dragKey || dragKey === row.key) return;
      const keys = movable.map((r) => r.key).filter((k) => k !== dragKey);
      keys.splice(keys.indexOf(row.key) + (after ? 1 : 0), 0, dragKey);
      saveLayout(keys, hiddenKeys());
    });
    return li;
  }));
}

function hiddenKeys() {
  return (state.sections || []).filter((r) => r.hidden).map((r) => r.key);
}

function toggled(key, hide) {
  const keys = hiddenKeys().filter((k) => k !== key);
  return hide ? [...keys, key] : keys;
}

function moveTo(key, index) {
  const keys = state.sections.filter((r) => !r.fixed).map((r) => r.key).filter((k) => k !== key);
  keys.splice(Math.max(0, Math.min(index, keys.length)), 0, key);
  saveLayout(keys, hiddenKeys());
}

async function saveLayout(order, hidden) {
  // Move the sections on the page right away (this also keeps any hand edits),
  // then store the layout so future rebuilds use it too.
  const cv = $("cv");
  for (const key of order) {
    const node = [...cv.querySelectorAll("section[data-section]")].find((n) => n.dataset.section === key);
    if (node) cv.append(node);
  }
  cv.querySelectorAll("section[data-section]").forEach((n) => { n.hidden = hidden.includes(n.dataset.section); });
  state.sections = [
    ...state.sections.filter((r) => r.fixed),
    ...order.map((k) => state.sections.find((r) => r.key === k)).filter(Boolean),
  ].map((r) => ({ ...r, hidden: hidden.includes(r.key) }));
  renderSections();
  await savingEdits;
  try {
    render(await api("POST", "/api/cv/layout", { order, hidden, html: cv.innerHTML }));
  } catch (err) {
    showNotice(err.message, true);
  }
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
    paid.label = "Best quality (paid, needs an API key)";
    paid.append(new Option(next.claude_available ? "Claude" : "Claude: add your API key", modelValue("claude")));
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
  const key = catalog.api_key;
  const wantsClaude = backend === "claude";
  $("key-form").hidden = !wantsClaude || key.set;
  $("key-status").hidden = !wantsClaude || !key.set;
  $("key-status-text").textContent = key.source === "environment"
    ? "Using the key from ANTHROPIC_API_KEY."
    : `Key saved (${key.hint}).`;
  $("key-remove").hidden = key.source !== "saved";
  if (wantsClaude && !key.set) {
    text = "The best writing and fastest updates.";
  } else if (wantsClaude) {
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
  if (backend === "claude" && !catalog.api_key.set) {
    updateModelNote();  // show the key box; switch once a key is saved
    $("key-input").focus();
    return;
  }
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

async function saveKey(e) {
  e.preventDefault();
  const key = $("key-input").value.trim();
  if (!key) { $("key-input").focus(); return; }
  await withBusy("Checking your key with Anthropic…", async () => {
    render(await api("POST", "/api/models/key", { key }));
    $("key-input").value = "";
    showNotice("");
    await loadModels();
  });
}

async function removeKey() {
  if (!confirm("Remove the saved API key from this computer?")) return;
  try {
    render(await api("DELETE", "/api/models/key"));
  } catch (err) {
    showNotice(err.message, true);
  }
  loadModels();
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
$("target").addEventListener("change", (e) => saveTarget(e.target.value));
$("page-size-select").addEventListener("change", (e) => saveSettings({ page_size: e.target.value }));
$("fit").addEventListener("change", (e) => saveSettings({ fit_one_page: e.target.checked }));
document.querySelectorAll("#template-picker button").forEach((b) =>
  b.addEventListener("click", () => saveSettings({ template: b.dataset.template })));
$("target").addEventListener("input", () => { state.target = $("target").value; scheduleLayout(); });
document.fonts?.ready.then(() => state && (layoutPages(), runChecks()));
$("cv").addEventListener("input", () => { scheduleEditSave(); scheduleLayout(); });
$("cv").addEventListener("paste", (e) => {
  // Paste as plain text so formatting from other apps doesn't leak into the CV.
  e.preventDefault();
  document.execCommand("insertText", false, e.clipboardData.getData("text/plain"));
});
$("learn").addEventListener("click", learnFromEdits);
$("pdf").addEventListener("click", downloadPdf);
$("docx").addEventListener("click", () => downloadFile("/api/export/cv.docx", "Making your Word document…"));
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
$("version-select").addEventListener("change", (e) => {
  if (e.target.value === NEW_VERSION) {
    e.target.value = state.active.id;
    switchTab("applications");
    showAppForm(true);
  } else openVersion(e.target.value);
});
$("new-app").addEventListener("click", () => showAppForm(true));
$("app-cancel").addEventListener("click", () => showAppForm(false));
$("app-form").addEventListener("submit", createApplication);
$("download-btn").addEventListener("click", downloadModel);
$("key-form").addEventListener("submit", saveKey);
$("key-remove").addEventListener("click", removeKey);
window.addEventListener("focus", () => { if (!downloadPoll) loadModels(); });

api("GET", "/api/state").then(render).catch((err) => showNotice(err.message, true));
loadModels();
