"use strict";
// The PhD tab: a checklist of what a strong academic CV needs (each with a quick fix),
// the PhD CV itself, and emailing professors. Uses helpers from app.js and extras.js.

const RESEARCH_RE = /research|\blab\b|laborator|\bRA\b|thesis|scientist|fellow/i;
const PHD_CV_ROLE = "PhD applications";

function researchRoles(m) {
  return m.experience.filter((e) => e.kind === "research" || RESEARCH_RE.test(`${e.role} ${e.organization}`));
}

function latestDegree(m) {
  return [...m.education].sort((a, b) => (b.end || b.start || "").localeCompare(a.end || a.start || ""))[0];
}

function isPaper(a) {
  return ["publication", "talk", "poster", "presentation"].includes((a.kind || "").toLowerCase());
}

function phdCv() {
  return state.versions.find((v) => v.kind === "phd" && v.role === PHD_CV_ROLE && !v.company);
}

// ---- small forms in the modal ----

function inputRow(pairs) {
  const row = el("div", "phd-form-row");
  pairs.forEach(([label, input]) => {
    const f = el("label", "field");
    f.append(el("span", "field-label", label), input);
    row.append(f);
  });
  return row;
}

function textInput(value = "", placeholder = "") {
  const i = el("input");
  i.value = value || "";
  i.placeholder = placeholder;
  return i;
}

function selectInput(options, value) {
  const s = el("select");
  options.forEach(([v, label]) => s.append(new Option(label, v)));
  s.value = value || options[0][0];
  return s;
}

async function saveAndRefresh(memory) {
  $("modal").close();
  await saveMemory(memory, "Saving…");
}

function fixInterests() {
  const area = el("textarea");
  area.rows = 5;
  area.value = state.memory.research_interests.join("\n");
  area.placeholder = "One per line, e.g.\nExposome data science\nEnvironmental epidemiology\nHigh-dimensional statistical methods\nReproducible research software";
  openModal("Research interests", [
    el("p", "hint", "4–8 short topics you want to research. They become the line at the top of your PhD CV, and each application reorders them to match the programme."),
    area,
  ], [{ label: "Cancel" }, { label: "Save", primary: true, onClick: () => {
    const memory = structuredClone(state.memory);
    memory.research_interests = area.value.split("\n").map((s) => s.trim()).filter(Boolean);
    saveAndRefresh(memory);
    return false;
  } }]);
  area.focus();
}

function fixSupervisors() {
  const roles = researchRoles(state.memory);
  const inputs = roles.map((r) => [r, textInput(r.supervisor, "e.g. Prof. Jane Wong")]);
  openModal("PIs and supervisors", [
    el("p", "hint", "Committees often know the people you worked with, and they're likely your referees. Shown as \"PI: …\" under each research role."),
    ...inputs.map(([r, i]) => inputRow([[[r.role, r.organization].filter(Boolean).join(" · "), i]])),
  ], [{ label: "Cancel" }, { label: "Save", primary: true, onClick: () => {
    const memory = structuredClone(state.memory);
    inputs.forEach(([r, i]) => { memory.experience.find((e) => e.id === r.id).supervisor = i.value.trim(); });
    saveAndRefresh(memory);
    return false;
  } }]);
}

function fixThesis() {
  const inputs = state.memory.education.map((e) => [e, textInput(e.thesis, "e.g. Exposome-wide association of air pollution (Supervisor: Prof. …)")]);
  openModal("Final-year project or thesis", [
    el("p", "hint", "Title, and supervisor if you had one. It's shown as one line under the degree. If it was real research, also add it as a research project in the Memory tab so it gets a full entry under Research Experience."),
    ...inputs.map(([e, i]) => inputRow([[[e.qualification, e.field, e.institution].filter(Boolean).join(", "), i]])),
  ], [{ label: "Cancel" }, { label: "Save", primary: true, onClick: () => {
    const memory = structuredClone(state.memory);
    inputs.forEach(([e, i]) => { memory.education.find((x) => x.id === e.id).thesis = i.value.trim(); });
    saveAndRefresh(memory);
    return false;
  } }]);
}

function listEditor({ title, intro, items, blank, fields, addLabel, onSave }) {
  const list = el("div", "phd-list");
  const rows = [];
  const addRow = (item) => {
    const box = el("div", "phd-list-item");
    const inputs = {};
    fields.forEach((group) => {
      box.append(inputRow(group.map(([key, label, kind, extra]) => {
        inputs[key] = kind === "select" ? selectInput(extra, item[key]) : textInput(item[key], extra);
        return [label, inputs[key]];
      })));
    });
    const entry = { item, inputs, box };
    box.append(button("Remove", "small danger", () => { box.remove(); rows.splice(rows.indexOf(entry), 1); }));
    rows.push(entry);
    list.append(box);
  };
  items.forEach(addRow);
  if (!items.length) addRow({ ...blank });
  openModal(title, [el("p", "hint", intro), list, button(addLabel, "small", () => addRow({ ...blank }))], [
    { label: "Cancel" },
    { label: "Save", primary: true, onClick: () => {
      const values = rows.map(({ item, inputs }) => {
        const out = { ...item };
        Object.entries(inputs).forEach(([k, i]) => { out[k] = i.value.trim(); });
        return out;
      });
      onSave(values);
      return false;
    } },
  ]);
}

function fixReferees() {
  listEditor({
    title: "Referees",
    intro: "Usually 2–3 people who know your research: PIs and supervisors first, then a lecturer who taught you. Ask them before listing them. They're shown under References (left off US applications, which collect letters separately).",
    items: state.memory.referees,
    blank: { name: "", title: "", organization: "", email: "", phone: "", relationship: "" },
    addLabel: "+ Add a referee",
    fields: [[["name", "Name", "text", "Prof. Jane Wong"], ["title", "Position", "text", "Associate Professor"]],
             [["organization", "Department and university", "text", "JC School of Public Health, CUHK"], ["email", "Email", "text", ""]],
             [["relationship", "How they know you", "text", "Supervisor, C-FIST Lab (2025–)"]]],
    onSave: (values) => {
      const memory = structuredClone(state.memory);
      memory.referees = values.filter((r) => r.name);
      saveAndRefresh(memory);
    },
  });
}

const PAPER_KINDS = [["publication", "Paper"], ["talk", "Talk or poster"]];
const PAPER_STATUS = [["", "—"], ["published", "Published"], ["accepted", "Accepted"], ["under review", "Under review"],
                      ["in preparation", "In preparation"]];

function fixPapers() {
  listEditor({
    title: "Publications and presentations",
    intro: "Papers (including under review or in preparation, marked honestly), posters and talks. They're written as citations with your name in bold. Nothing yet? That's normal for a new graduate: skip this.",
    items: state.memory.achievements.filter(isPaper),
    blank: { kind: "publication", title: "", authors: "", issuer: "", date: "", status: "", link: "" },
    addLabel: "+ Add a paper, poster or talk",
    fields: [[["kind", "Type", "select", PAPER_KINDS], ["status", "Status", "select", PAPER_STATUS]],
             [["title", "Title", "text", ""]],
             [["authors", "Authors, in order", "text", "Wong J, Chow K, Lee A"], ["issuer", "Journal or conference", "text", ""]],
             [["date", "Year or date", "text", "2025"], ["link", "DOI or link", "text", ""]]],
    onSave: (values) => {
      const memory = structuredClone(state.memory);
      const others = memory.achievements.filter((a) => !isPaper(a));
      memory.achievements = [...others, ...values.filter((p) => p.title)];
      saveAndRefresh(memory);
    },
  });
}

function editInMemory(section, index = -1) {
  editing = section === "profile" ? { section } : { section, index };
  switchTab("memory");
  renderMemory();
  $("memory-view").scrollIntoView({ behavior: "smooth" });
}

// ---- the checklist ----

function phdChecks() {
  const m = state.memory;
  const roles = researchRoles(m);
  const degree = latestDegree(m);
  const papers = m.achievements.filter(isPaper);
  const links = m.profile.links.map((l) => `${l.label} ${l.url}`).join(" ").toLowerCase();
  const withoutPi = roles.filter((r) => !r.supervisor);
  return [
    { done: m.research_interests.length > 0, label: "Research interests",
      detail: m.research_interests.length ? m.research_interests.join(" · ") : "A line of 4–8 topics at the top of the CV.", fix: fixInterests },
    { done: roles.length > 0, label: "Research experience",
      detail: roles.length ? roles.map((r) => r.role || r.organization).join(", ")
                           : "Research roles (RA, lab work, thesis research). Add them on the left, or edit a job and set its type to research.",
      fix: () => editInMemory("experience"), fixLabel: roles.length ? "Edit" : "Add" },
    { done: roles.length > 0 && !withoutPi.length, label: "PIs named on research roles",
      detail: !roles.length ? "Add research experience first." : withoutPi.length ? `Missing for: ${withoutPi.map((r) => r.role || r.organization).join(", ")}` : "Shown as \"PI: …\" under each role.",
      fix: roles.length ? fixSupervisors : null },
    { done: !!degree?.thesis, label: "Final-year project or thesis",
      detail: degree?.thesis || "One line under your degree: title and supervisor.", fix: degree ? fixThesis : () => editInMemory("education") },
    { done: !!degree && (!!degree.grade || degree.highlights.some((h) => /course/i.test(h))), optional: true, label: "GPA and relevant coursework",
      detail: "GPA if it's 3.5 or above, and 5–8 methods-heavy courses.", fix: degree ? () => editInMemory("education", m.education.indexOf(degree)) : null },
    { done: papers.length > 0, optional: true, label: "Publications, posters and talks",
      detail: papers.length ? `${papers.length} listed${papers.some((p) => !p.authors) ? " (add authors to show them as citations)" : ""}` : "Only if you have any, including in preparation.",
      fix: fixPapers },
    { done: m.referees.length >= 2, label: "Referees",
      detail: m.referees.length ? m.referees.map((r) => r.name).join(", ") + (m.referees.length < 2 ? " · usually 2–3" : "") : "2–3 people who know your research.",
      fix: fixReferees },
    { done: !!m.profile.email && m.profile.links.length > 0, label: "Contact details and links",
      detail: /github|scholar|orcid/.test(links) ? "Email and links set." : "Email, plus GitHub (and Google Scholar or ORCID if you have them).",
      fix: () => editInMemory("profile") },
  ];
}

function renderPhd() {
  if (!state) return;
  const checks = phdChecks();
  const required = checks.filter((c) => !c.optional);
  const done = required.filter((c) => c.done).length;
  $("phd-score").textContent = `${done} of ${required.length} done`;
  $("phd-score").classList.toggle("complete", done === required.length);
  $("phd-checks").replaceChildren(...checks.map((c) => {
    const row = el("div", `phd-check ${c.done ? "ok" : c.optional ? "optional" : "todo"}`);
    row.append(el("span", "icon", c.done ? "✓" : c.optional ? "○" : "!"));
    const body = el("div");
    body.append(el("div", "", c.label + (c.optional ? " (optional)" : "")), el("div", "hint", c.detail));
    row.append(body);
    if (c.fix) row.append(button(c.fixLabel || (c.done ? "Edit" : "Fix"), `small${c.done ? "" : " primary"}`, c.fix));
    return row;
  }));

  const cv = phdCv();
  const box = $("phd-cv");
  if (!cv) {
    box.replaceChildren(button("Create my PhD CV", "primary", createPhdCv),
                        el("span", "hint", required.every((c) => c.done) ? "Ready." : "You can create it now and it updates as you fix the checklist."));
  } else {
    box.replaceChildren(
      button("Open it", "primary", () => openVersion(cv.id)),
      button("Download PDF", "", async () => { if (state.active.id !== cv.id) await openVersion(cv.id); downloadPdf(); }),
      button("Rebuild with latest memory", "", async () => {
        await flushEdits();
        await withBusy(busyText("Rewriting your PhD CV…"), async () => {
          if (state.active.id !== cv.id) render(await api("POST", "/api/versions/active", { id: cv.id }));
          render(await api("POST", "/api/build"));
        });
      }, "Rewrites it from your memory; replaces hand edits"),
      el("span", "hint", `Last updated ${new Date(cv.updated || cv.created).toLocaleDateString()}`));
  }

  const apps = state.versions.filter((v) => v.kind === "phd" && v !== cv);
  const list = $("phd-apps");
  if (!apps.length) { list.replaceChildren(); return; }
  list.replaceChildren(el("h3", "", "Your PhD applications"), ...apps.map((v) => {
    const row = el("div", "phd-app");
    const info = el("div");
    const name = el("div", "name", v.name);
    name.append(el("span", `status ${v.status}`, v.status));
    info.append(name, el("div", "hint", [v.supervisor, v.company].filter(Boolean).join(" · ")));
    const actions = el("div", "actions");
    actions.append(button("Email professor", "small", () => professorDialog(v)),
                   button("CV", "small", () => openVersion(v.id)),
                   button("Statement", "small", () => openVersion(v.id, "letter")),
                   button("Interview prep", "small", () => openVersion(v.id, "interview")));
    row.append(info, actions);
    const reminder = followUpReminder(v);
    if (reminder) row.append(reminder);
    return row;
  }));
}

async function createPhdCv() {
  await flushEdits();
  await withBusy(busyText("Writing your PhD CV…"), async () => {
    const next = await api("POST", "/api/versions", { company: "", role: PHD_CV_ROLE, kind: "phd",
                                                        region: state.settings.region || "" });
    render(next);
    showNotice(next.notice || "Your PhD CV is ready. Check it, then download the PDF.");
    switchTab("cv");
  });
}

$("phd-review").addEventListener("click", () => { switchTab("memory"); runReview(); });
$("phd-email").addEventListener("click", () => professorSearch(null));
$("phd-programme").addEventListener("click", () => {
  switchTab("applications");
  showAppForm(true);
  $("app-form").elements.kind.value = "phd";
  relabelAppForm();
});
