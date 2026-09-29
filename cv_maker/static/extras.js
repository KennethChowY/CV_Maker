"use strict";
// Helpers beyond writing the CV: truth check, "strengthen my CV" questions, interview prep,
// LinkedIn text, job ads from links, follow-up emails, and country, language and photo.
// Uses the helpers and `state` defined in app.js.

// ---------- Small helpers ----------

function openModal(title, body, actions) {
  const dialog = $("modal");
  $("modal-title").textContent = title;
  $("modal-body").replaceChildren(...[].concat(body));
  $("modal-actions").replaceChildren(...actions.map((a) => {
    const b = button(a.label, a.primary ? "primary" : "", async (e) => {
      if (a.onClick && (await a.onClick(e)) === false) return;  // returning false keeps it open
      if (dialog.open) dialog.close();
    }, a.title);
    b.disabled = !!a.disabled;
    return b;
  }));
  if (!dialog.open) dialog.showModal();
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = el("textarea");
    area.value = text;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  if (btn) {
    const label = btn.textContent;
    btn.textContent = "Copied ✓";
    setTimeout(() => { btn.textContent = label; }, 1500);
  }
}

function copyButton(getText, label = "Copy") {
  const b = button(label, "small", () => copyText(getText(), b), "Copy to the clipboard");
  return b;
}

function thinkingRow(text) {
  const row = el("div", "thinking");
  row.append(el("div", "spinner"), el("span", "", state.ai_status.local ? `${text} A local model can take a minute or two.` : text));
  return row;
}

function daysSince(isoDate) {
  const then = new Date(`${isoDate.slice(0, 10)}T00:00:00`);
  return Math.floor((Date.now() - then.getTime()) / 86400000);
}

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// ---------- Is it all true? ----------

let truthVersion = null;

const squash = (text) => text.replace(/\s+/g, " ").trim();

// The CV element (bullet, line or heading) that contains the quoted words.
function findQuote(quote) {
  const wanted = squash(quote).toLowerCase();
  if (!wanted) return null;
  const candidates = [...$("cv").querySelectorAll("li, p, .cv-entry-title, .cv-entry-org, .cv-entry-dates, .cv-headline")];
  const find = (needle) => candidates.find((n) => squash(n.textContent).toLowerCase().includes(needle));
  return find(wanted) || find(wanted.slice(0, 40)) || null;
}

function flash(node) {
  node.scrollIntoView({ behavior: "smooth", block: "center" });
  node.classList.add("flash");
  setTimeout(() => node.classList.remove("flash"), 1600);
}

function replaceQuote(node, quote, replacement) {
  const text = squash(node.textContent);
  const at = text.toLowerCase().indexOf(squash(quote).toLowerCase());
  if (!replacement && node.tagName === "LI" && (at <= 0 && text.length - squash(quote).length < 5)) {
    node.remove();  // the whole bullet was unsupported
  } else if (at >= 0) {
    node.textContent = text.slice(0, at) + replacement + text.slice(at + squash(quote).length);
    flash(node);
  } else {
    node.textContent = replacement;
    flash(node);
  }
  $("cv").dispatchEvent(new Event("input"));  // saves the edit and refreshes the checks
}

function renderTruth(issues) {
  const list = $("truth-list");
  if (!issues.length) {
    list.replaceChildren(el("div", "check-item ok truth-ok", "✓ Everything on this CV is backed up by your memory."));
    return;
  }
  list.replaceChildren(...issues.map((issue) => {
    const row = el("div", "truth-item");
    const node = findQuote(issue.quote);
    if (issue.quote) row.append(el("div", "truth-quote", `“${issue.quote}”`));
    row.append(el("div", "", issue.problem));
    if (issue.suggestion) row.append(el("div", "detail", `Suggested: ${issue.suggestion}`));
    const actions = el("div", "row");
    if (node) actions.append(button("Show me", "small", () => flash(node)));
    if (node && issue.suggestion) {
      actions.append(button("Use the suggestion", "small primary", () => { replaceQuote(node, issue.quote, issue.suggestion); row.remove(); }));
    } else if (node && node.tagName === "LI") {
      actions.append(button("Remove it", "small", () => { replaceQuote(node, issue.quote, ""); row.remove(); }));
    }
    actions.append(button("It's true: add it to memory", "small", () => {
      const input = $("input");
      input.value = `About "${issue.quote || issue.problem}": this is true. The details are: `;
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
      showNotice("Add the details on the left and click 'Add to memory', so future CVs can say it too.");
    }, "The memory is missing this fact: add it"));
    row.append(actions);
    return row;
  }));
}

async function runTruthCheck() {
  await flushEdits();
  $("check-panel").open = true;
  $("truth-list").replaceChildren(thinkingRow("Comparing every line with your memory…"));
  $("truth-run").disabled = true;
  try {
    const { issues } = await api("POST", "/api/truth-check", { text: $("cv").innerText });
    truthVersion = state.active.id;
    renderTruth(issues);
  } catch (err) {
    $("truth-list").replaceChildren(el("div", "check-item warn", err.message));
  } finally {
    $("truth-run").disabled = !state.ai_enabled;
  }
}

// ---------- Strengthen my CV ----------

async function strengthen() {
  const res = await withBusy(busyText("Finding what would make your CV stronger…"), () => api("POST", "/api/strengthen"));
  if (!res) return;
  if (!res.questions.length) {
    showNotice("Your memory already answers the usual questions. Nice work.");
    return;
  }
  const rows = res.questions.map((q) => {
    const wrap = el("label", "field strengthen-q");
    if (q.about) wrap.append(el("span", "field-label", q.about));
    wrap.append(el("span", "question", q.question));
    const answer = el("textarea");
    answer.rows = 2;
    answer.placeholder = "Your answer (skip it if you're not sure)";
    wrap.append(answer);
    return { q, answer, wrap };
  });
  const intro = el("p", "hint", "Answer the ones you can; skip the rest. Rough numbers are fine (\"about 200\"), but only give ones you're sure are true.");
  openModal("Strengthen my CV", [intro, ...rows.map((r) => r.wrap)], [
    { label: "Cancel" },
    {
      label: "Add answers to memory", primary: true,
      onClick: async () => {
        const answered = rows.filter((r) => r.answer.value.trim());
        if (!answered.length) { rows[0].answer.focus(); return false; }
        const text = "My answers to questions about my CV:\n\n" + answered.map((r) =>
          `${r.q.about ? `(${r.q.about}) ` : ""}${r.q.question}\n→ ${r.answer.value.trim()}`).join("\n\n");
        $("modal").close();
        $("input").value = text;
        if (state.ai_enabled) await addToMemory();
        else showNotice("Choose an AI model in the top-left box, then click 'Add to memory' to save your answers.");
      },
    },
  ]);
  rows[0].answer.focus();
}

// ---------- Interview prep ----------

function prepAsText(prep) {
  const lines = [`Interview prep: ${state.active.name}`, ""];
  prep.questions.forEach((q, i) => {
    lines.push(`${i + 1}. ${q.question}`);
    if (q.why) lines.push(`   Why they ask: ${q.why}`);
    q.answer.forEach((a) => lines.push(`   • ${a}`));
    lines.push("");
  });
  if (prep.ask_them.length) {
    lines.push("Questions to ask them:");
    prep.ask_them.forEach((q) => lines.push(`• ${q}`));
  }
  return lines.join("\n");
}

function renderPrep() {
  const active = state.active;
  const general = active.id === "general";
  const prep = state.prep || {};
  const has = !!(prep.questions && prep.questions.length);
  $("prep-for").textContent = general ? "" : `Interview prep for ${active.name}`;
  $("prep-write").hidden = general;
  $("prep-write").disabled = !state.ai_enabled;
  $("prep-write").textContent = has ? "Prepare again" : "Prepare me";
  $("prep-empty").hidden = has && !general;
  const text = $("prep-empty-text");
  if (general) {
    text.replaceChildren("Interview prep is for a specific job. Open one of your applications, then come back here.");
    const invited = state.versions.filter((v) => ["Interview", "Applied", "Offer"].includes(v.status));
    const pick = invited.length ? invited : state.versions;
    if (pick.length) {
      const choices = el("div", "row center");
      pick.slice(0, 4).forEach((v) => choices.append(button(v.name, "small", () => openVersion(v.id, "interview"))));
      text.append(choices);
    }
  } else {
    text.textContent = state.ai_enabled
      ? "Get the questions you're most likely to be asked for this job, with talking points from your real experience, and good questions to ask them."
      : "Choose an AI model in the top-left box to get interview questions and talking points for this job.";
  }
  const box = $("prep");
  if (!has || general) { box.replaceChildren(); return; }
  const tools = el("div", "row end");
  tools.append(copyButton(() => prepAsText(prep), "Copy all"));
  const cards = prep.questions.map((q, i) => {
    const card = el("details", "prep-card");
    card.open = i < 3;
    const summary = el("summary");
    summary.append(el("span", "num", `${i + 1}`), el("span", "", q.question));
    card.append(summary);
    if (q.why) card.append(el("p", "hint", q.why));
    const ul = el("ul");
    q.answer.forEach((a) => ul.append(el("li", "", a)));
    card.append(ul);
    return card;
  });
  const ask = el("div", "prep-ask card");
  ask.append(el("h2", "", "Questions to ask them"));
  const ul = el("ul");
  prep.ask_them.forEach((q) => ul.append(el("li", "", q)));
  ask.append(ul);
  box.replaceChildren(tools, ...cards, ...(prep.ask_them.length ? [ask] : []));
}

async function writePrep() {
  await withBusy(busyText("Preparing likely questions and your answers…"), async () => {
    render(await api("POST", "/api/interview"));
    showNotice("");
  });
}

// ---------- LinkedIn ----------

function copyField(label, text, limit) {
  const block = el("div", "li-field card");
  const head = el("div", "li-head");
  head.append(el("h2", "", label));
  if (limit) head.append(el("span", `li-count${text.length > limit ? " over" : ""}`, `${text.length} / ${limit}`));
  head.append(copyButton(() => text));
  block.append(head, el("div", "li-text", text));
  return block;
}

function renderLinkedIn() {
  const li = state.linkedin || {};
  const has = !!(li.headline || li.about);
  $("linkedin-empty").hidden = has;
  $("linkedin-write").textContent = has ? "Rewrite" : "Write my LinkedIn text";
  $("linkedin-write").disabled = !state.ai_enabled;
  if (!has) { $("linkedin").replaceChildren(); return; }
  const parts = [copyField("Headline", li.headline || "", 220), copyField("About", li.about || "", 2600)];
  (li.experience || []).forEach((r) => parts.push(copyField(`Experience: ${[r.title, r.company].filter(Boolean).join(" at ")}`, r.description || "")));
  if (li.generated_at) parts.push(el("p", "hint", `Written ${new Date(li.generated_at).toLocaleString()}. Rewrite it after big updates to your memory.`));
  $("linkedin").replaceChildren(...parts);
}

async function writeLinkedIn() {
  if (state.linkedin?.headline && !confirm("Write new LinkedIn text? This replaces the current text.")) return;
  await withBusy(busyText("Writing your LinkedIn text…"), async () => {
    render(await api("POST", "/api/linkedin"));
    showNotice("");
  });
}

// ---------- Job ad from a link ----------

async function fetchJobAd() {
  const f = $("app-form").elements;
  const url = f.link.value.trim();
  if (!url) { f.link.focus(); return; }
  await withBusy("Reading the job ad…", async () => {
    const { text } = await api("POST", "/api/job-ad", { url: /^https?:\/\//i.test(url) ? url : `https://${url}` });
    f.target.value = text;
    showNotice("Got the job ad. Check it below and trim anything that isn't part of the ad.");
  });
}

// ---------- Follow-ups ----------

const FOLLOW_UP_DAYS = 7;

function followUpDue(v) {
  return v.status === "Applied" && !!v.applied && !v.followed_up && daysSince(v.applied) >= FOLLOW_UP_DAYS;
}

// A reminder line for an application card, or null.
function followUpReminder(v) {
  if (v.followed_up && v.status === "Applied") {
    return el("div", "reminder done", `Followed up on ${new Date(`${v.followed_up}T00:00:00`).toLocaleDateString()}.`);
  }
  if (!followUpDue(v)) return null;
  const box = el("div", "reminder");
  box.append(el("span", "", `Applied ${daysSince(v.applied)} days ago with no reply yet. A short, polite follow-up email often gets things moving.`));
  const draft = button("Draft follow-up email", "small primary", () => draftFollowUp(v));
  draft.disabled = !state.ai_enabled;
  if (!state.ai_enabled) draft.title = "Choose an AI model first";
  box.append(draft, button("Already done", "small", () => updateApplication(v.id, { followed_up: today() }), "Mark as followed up"));
  return box;
}

async function draftFollowUp(v) {
  const email = await withBusy(busyText("Drafting your follow-up email…"), () => api("POST", `/api/versions/${v.id}/follow-up`));
  if (!email) return;
  emailDialog(`Follow-up: ${v.name}`, email,
              "Send it to the recruiter or hiring manager if you know who they are; otherwise reply to the application confirmation email.",
              { label: "Mark as sent", primary: true, onClick: () => updateApplication(v.id, { followed_up: today() }) });
}

const FIT_NOTES = {
  strong: "Good match: their research is close to your own work.",
  partial: "Partial match: you share methods or questions, but not the field. The email says honestly what you'd bring and what you want to learn.",
  weak: "Weak match: their research is quite far from your experience, so the email can't honestly claim a close link. Check it's the right person, tell the app what draws you to their work, or consider a professor closer to what you've done.",
};

async function draftSupervisorEmail(v, options = {}) {
  const email = await withBusy(busyText("Drafting an email to your potential supervisor…"),
                               () => api("POST", `/api/versions/${v.id}/supervisor-email`, options));
  if (!email) return;
  const notes = [];
  if (email.fit) {
    const fit = el("div", `fit-note ${email.fit}`);
    fit.append(el("strong", "", FIT_NOTES[email.fit]));
    if (email.overlap) fit.append(el("div", "", `The link: ${email.overlap}`));
    if (email.paper) fit.append(el("div", "", `Paper it mentions: “${email.paper}”`));
    notes.push(fit);
  }
  const instruction = el("input");
  instruction.placeholder = "Change something? e.g. \"warmer\", \"mention I want to learn MRI methods\", \"use a different paper\"";
  const rewrite = el("div", "rewrite");
  rewrite.append(instruction);
  emailDialog(`Email to a potential supervisor: ${v.name}`, email,
              "Read it through and make it yours: fill in anything in [square brackets], attach your academic CV (Download PDF on the CV tab), and send it from your university email if you have one. If there's no reply in two weeks, one polite follow-up is fine.",
              { label: "Done", primary: true },
              { before: notes, after: [rewrite],
                extra: { label: "Rewrite", title: "Write a new draft, following your instruction if you gave one",
                         onClick: () => { $("modal").close(); draftSupervisorEmail(v, { instruction: instruction.value }); return false; } } });
}

function emailDialog(title, email, tipText, finalAction, more = {}) {
  const subject = el("input");
  subject.value = email.subject;
  const body = el("textarea");
  body.rows = 10;
  body.value = email.body;
  const field = (label, input) => { const l = el("label", "field"); l.append(el("span", "field-label", label), input); return l; };
  const tip = el("p", "hint", tipText);
  openModal(title, [...(more.before || []), field("Subject", subject), field("Email", body), ...(more.after || []), tip], [
    ...(more.extra ? [more.extra] : []),
    { label: "Copy", onClick: (e) => { copyText(`Subject: ${subject.value}\n\n${body.value}`, e.currentTarget); return false; } },
    {
      label: "Open in my email app",
      onClick: () => {
        window.location.href = `mailto:?subject=${encodeURIComponent(subject.value)}&body=${encodeURIComponent(body.value)}`;
        return false;
      },
    },
    finalAction,
  ]);
}

// ---------- Email a professor (PhD) ----------

function paperList(title, works) {
  const box = el("div", "papers");
  box.append(el("h3", "", title));
  const ul = el("ul");
  works.forEach((w) => {
    const li = el("li");
    li.append(el("span", "paper-title", w.title), el("span", "hint", ` · ${[w.year, w.venue].filter(Boolean).join(", ")}`));
    ul.append(li);
  });
  box.append(ul);
  return box;
}

function showProfessor(v, prof) {
  const body = [];
  const head = el("div", "prof-head");
  head.append(el("strong", "", prof.name), el("span", "hint", ` · ${prof.institutions.join(", ")}`));
  body.push(head);
  if (prof.topics.length) {
    const chips = el("div", "chips");
    prof.topics.forEach((t) => chips.append(el("span", "chip", t)));
    body.push(chips);
  }
  if (prof.recent.length) body.push(paperList("Recent papers", prof.recent.slice(0, 6)));
  if (prof.cited.length) body.push(paperList("Most cited", prof.cited.slice(0, 3)));
  const src = el("p", "hint");
  const a = el("a", "", "OpenAlex");
  a.href = prof.source;
  a.target = "_blank";
  a.rel = "noopener";
  src.append("From ", a, ", an open index of academic papers. Not who you meant? Search again.");
  body.push(src);
  const interest = el("textarea");
  interest.rows = 3;
  interest.value = prof.interest || "";
  interest.placeholder = "e.g. Their air-pollution cohort work: I'd like to apply exposome-wide methods to it, and learn how they handle exposure measurement error.";
  const interestField = el("label", "field");
  interestField.append(el("span", "field-label", "What draws you to their work? Optional, but it's what makes the email sound like you."), interest);
  body.push(interestField);
  if (!state.ai_enabled) body.push(el("p", "hint warn", "Choose an AI model in the top-left box to draft the email."));
  openModal(`Email a professor: ${v.name}`, body, [
    { label: "Search again", onClick: () => { professorSearch(v, prof.name); return false; } },
    { label: "Draft the email", primary: true, disabled: !state.ai_enabled,
      onClick: () => { $("modal").close(); draftSupervisorEmail(v, { interest: interest.value }); return false; } },
  ]);
}

// Step 1: who. `v` is the PhD application, or null to start a new one.
function professorSearch(v, name = "", institution = "") {
  const nameIn = el("input");
  nameIn.value = name || v?.supervisor || "";
  nameIn.placeholder = "e.g. Jane Wong";
  const instIn = el("input");
  instIn.value = institution || v?.company || "";
  instIn.placeholder = "e.g. CUHK or The Chinese University of Hong Kong";
  const field = (label, input) => { const l = el("label", "field"); l.append(el("span", "field-label", label), input); return l; };
  const results = el("div", "people");
  const search = async () => {
    if (!nameIn.value.trim()) { nameIn.focus(); return false; }
    results.replaceChildren(thinkingRow("Looking them up…"));
    try {
      const { people } = await api("POST", "/api/professor/search", { name: nameIn.value, institution: instIn.value });
      if (!people.length) {
        results.replaceChildren(el("p", "hint", "Nobody by that name was found. Check the spelling, or paste their lab page link into the application's 'Programme and research' box and draft the email from that."));
        return false;
      }
      results.replaceChildren(el("p", "hint", "Which one is it?"), ...people.map((p) => {
        const b = button("", "person", () => pickProfessor(v, p, instIn.value));
        b.append(el("strong", "", p.name), el("span", "hint", ` · ${p.institutions.join(", ") || "institution unknown"}`),
                 el("div", "hint", `${p.works} papers${p.topics.length ? ` · ${p.topics.slice(0, 3).join(", ")}` : ""}`));
        return b;
      }));
    } catch (err) {
      results.replaceChildren(el("p", "hint warn", err.message));
    }
    return false;
  };
  [nameIn, instIn].forEach((i) => i.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); search(); } }));
  const intro = el("p", "hint", "Type the professor's name. The app finds their papers, so your email can mention their actual research.");
  openModal(v ? `Email a professor: ${v.name}` : "Email a professor", [intro, field("Professor's name", nameIn),
    field("University", instIn), results], [{ label: "Cancel" }, { label: "Find their research", primary: true, onClick: search }]);
  nameIn.focus();
}

async function pickProfessor(v, person, institution) {
  $("modal").close();
  await withBusy(v ? "Reading their papers…" : busyText("Setting up a PhD application and your academic CV…"), async () => {
    if (!v) {  // start tracking this as a PhD application, with an academic CV to attach
      const next = await api("POST", "/api/versions", {
        company: institution.trim() || person.institutions[0] || "", role: "PhD", kind: "phd", supervisor: person.name,
        region: state.settings.region || "",
      });
      render(next);
      v = state.versions.find((x) => x.id === next.active.id);
    }
    const { professor } = await api("POST", `/api/versions/${v.id}/professor`, { id: person.id });
    render(await api("GET", "/api/state"));
    showProfessor(state.versions.find((x) => x.id === v.id) || v, professor);
  });
}

async function professorDialog(v) {
  if (v) {
    try {
      const { professor } = await api("GET", `/api/versions/${v.id}/professor`);
      if (professor && professor.name) { showProfessor(v, professor); return; }
    } catch { /* search instead */ }
  }
  professorSearch(v);
}

// ---------- Automatic backups ----------

function backupDialog() {
  const b = state.backup;
  const folder = el("input");
  folder.value = b.folder || b.suggested;
  const field = el("label", "field");
  field.append(el("span", "field-label", "Folder"), folder);
  const status = el("p", "hint", b.folder
    ? (b.last ? `On. Last backup ${new Date(b.last).toLocaleString()} · ${b.count} kept.` : "On. No backup yet.")
    : "Off.");
  const intro = el("p", "hint", "While this is on, the app saves a zip of your memory, CVs and letters to this folder, at most once an hour after you change something, and keeps the latest 30. Your API key is never included. A folder in iCloud Drive keeps them safe even if something happens to this computer.");
  const suggest = b.suggested.includes("CloudDocs") ? el("p", "hint", "Suggested: your iCloud Drive.") : el("span");
  const actions = [];
  if (b.folder) {
    actions.push({ label: "Turn off", onClick: () => saveSettings({ backup_dir: "" }) });
    actions.push({ label: "Back up now", onClick: async () => {
      await withBusy("Backing up…", async () => render(await api("POST", "/api/backup/now")));
      backupDialog();
      return false;
    } });
  }
  actions.push({ label: b.folder ? "Save" : "Turn on", primary: true, onClick: async () => {
    try {
      render(await api("POST", "/api/settings", { backup_dir: folder.value }));
      showNotice(`Automatic backups are on. They go to ${state.backup.folder}.`);
    } catch (err) {
      status.textContent = err.message;
      status.classList.add("warn");
      return false;
    }
  } });
  openModal("Automatic backups", [intro, field, suggest, status], actions);
}

// ---------- Spending ----------

function money(n) {
  return n < 0.01 && n > 0 ? "under $0.01" : `$${n.toFixed(2)}`;
}

function tokens(n) {
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n);
}

function renderUsage() {
  const line = $("usage-line");
  const u = state.usage;
  const m = u.month;
  const local = state.ai_status.local;
  if (!m.requests && !u.all.requests) { line.hidden = true; return; }
  line.hidden = false;
  const paid = m.requests - m.local;
  if (local && !paid) line.textContent = `Free: ${m.requests} requests this month ran on this computer`;
  else if (m.unpriced && !m.cost) line.textContent = `This month: ${paid} requests, ${tokens(m.input_tokens + m.output_tokens)} tokens`;
  else line.textContent = `This month: about ${money(m.cost)} · ${paid} requests`;
}

function usageDialog() {
  const u = state.usage;
  const table = (title, t) => {
    const box = el("div", "usage-table");
    box.append(el("h3", "", title));
    const rows = el("table");
    const head = el("tr");
    ["What", "Requests", "Tokens", "Cost"].forEach((h) => head.append(el("th", "", h)));
    rows.append(head);
    t.by_purpose.forEach((r) => {
      const tr = el("tr");
      [r.purpose, r.requests, tokens(r.tokens), r.cost ? money(r.cost) : "–"].forEach((c) => tr.append(el("td", "", String(c))));
      rows.append(tr);
    });
    const total = el("tr", "total");
    ["Total", t.requests, tokens(t.input_tokens + t.output_tokens), money(t.cost)].forEach((c) => total.append(el("td", "", String(c))));
    rows.append(total);
    box.append(rows);
    return box;
  };
  const notes = el("p", "hint", "Costs are estimates from the list prices of Anthropic's models. Requests to other services show tokens only; check that service's billing page for the exact cost. Free local models cost nothing.");
  openModal("AI usage", [table("This month", u.month), table("All time", u.all), notes], [{ label: "Close", primary: true }]);
}

// ---------- Country, language and photo ----------

function fillSelect(select, entries) {
  if (select.options.length === entries.length) return;
  select.replaceChildren(...entries.map(([value, label]) => new Option(label, value)));
}

function regionEntries() {
  return Object.entries(state.regions).map(([k, r]) => [k, k ? r.name : "Any country"]);
}

async function changeConventions(patch) {
  await flushEdits();
  if (patch.language && patch.language !== "en" && !state.ai_enabled) {
    showNotice("Translating the CV needs an AI model. Choose one in the top-left box first.", true);
    renderExtras();
    return;
  }
  if (state.cv_meta.edited && !confirm("This rewrites the CV, replacing your manual edits. Continue?")) {
    renderExtras();
    return;
  }
  const language = patch.language || state.active.language;
  const message = language !== "en" ? "Rewriting and translating your CV…" : "Rewriting your CV for that country…";
  await withBusy(busyText(message), async () => {
    await api("PATCH", `/api/versions/${state.active.id}`, patch);
    render(await api("POST", "/api/build"));
    showNotice("");
  });
}

async function resizedPhoto(file) {
  // Shrink big phone photos before upload: a CV photo is printed about 2.5 cm wide.
  const img = await createImageBitmap(file);
  const scale = Math.min(1, 600 / Math.max(img.width, img.height));
  const canvas = el("canvas");
  canvas.width = Math.round(img.width * scale);
  canvas.height = Math.round(img.height * scale);
  canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
}

async function uploadPhoto(file) {
  await flushEdits();
  await withBusy("Adding your photo…", async () => {
    const form = new FormData();
    let blob = file;
    try { blob = await resizedPhoto(file); } catch { /* keep the original */ }
    form.append("photo", blob, "photo.jpg");
    render(await api("POST", "/api/photo", form));
    const region = state.regions[state.active.region];
    showNotice(region && !region.photo
      ? `Photo saved. It's left off this CV because ${region.name} employers don't expect one; it shows on your other CVs.`
      : "");
  });
}

function photoDialog() {
  const region = state.regions[state.active.region] || state.regions[""];
  const body = [];
  const preview = $("cv").querySelector(".cv-photo");
  if (state.has_photo && preview) {
    const img = el("img", "photo-preview");
    img.src = preview.src;
    body.push(img);
  }
  body.push(el("p", "hint", "Photos are common on Hong Kong and European CVs. In the US and UK they're left off, to avoid bias, so CVs for those countries never show one."));
  if (state.has_photo) {
    const label = el("label", "check");
    const box = el("input");
    box.type = "checkbox";
    box.checked = !!state.settings.show_photo;
    box.disabled = !region.photo;
    box.addEventListener("change", () => saveSettings({ show_photo: box.checked }));
    label.append(box, region.photo ? "Show my photo on the CV" : `Show my photo (not on ${region.name} CVs)`);
    body.push(label);
  }
  const actions = [];
  if (state.has_photo) {
    actions.push({ label: "Remove photo", onClick: async () => {
      await flushEdits();
      await withBusy("Removing your photo…", async () => render(await api("DELETE", "/api/photo")));
    } });
  }
  actions.push({ label: state.has_photo ? "Choose another photo…" : "Choose a photo…", primary: !state.has_photo,
                 onClick: () => $("photo-file").click() });
  actions.push({ label: "Done", primary: state.has_photo });
  openModal("Photo", body, actions);
}

// ---------- Drawing ----------

function renderExtras() {
  if (truthVersion !== state.active.id) {
    $("truth-list").replaceChildren();
    truthVersion = state.active.id;
  }
  $("truth-run").disabled = !state.ai_enabled;
  $("truth-run").title = state.ai_enabled ? "" : "Choose an AI model first";

  fillSelect($("region-select"), regionEntries());
  fillSelect($("language-select"), Object.entries(state.languages));
  $("region-select").value = state.active.region || "";
  $("language-select").value = state.active.language || "en";
  const f = $("app-form").elements;
  fillSelect(f.region, regionEntries());
  fillSelect(f.language, Object.entries(state.languages));
  $("photo-btn").textContent = state.has_photo && state.settings.show_photo ? "Photo ✓" : "Photo";

  const due = state.versions.filter(followUpDue).length;
  const tab = document.querySelector('.tab[data-tab="applications"]');
  tab.textContent = "Applications";
  if (due) tab.append(el("span", "badge", String(due)));
  tab.title = due ? `${due} application${due > 1 ? "s" : ""} to follow up` : "";

  renderPrep();
  renderLinkedIn();
  renderUsage();
}

// ---------- Wiring ----------

$("truth-run").addEventListener("click", runTruthCheck);
$("email-professor").addEventListener("click", () => professorSearch(null));
$("auto-backup").addEventListener("click", backupDialog);
$("usage-line").addEventListener("click", usageDialog);
$("strengthen").addEventListener("click", strengthen);
$("prep-write").addEventListener("click", writePrep);
$("linkedin-write").addEventListener("click", writeLinkedIn);
$("fetch-ad").addEventListener("click", fetchJobAd);
$("region-select").addEventListener("change", (e) => changeConventions({ region: e.target.value }));
$("language-select").addEventListener("change", (e) => changeConventions({ language: e.target.value }));
$("photo-btn").addEventListener("click", photoDialog);
$("photo-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if ($("modal").open) $("modal").close();
  if (file) await uploadPhoto(file);
});
// The application form speaks about universities and programmes for PhD applications.
function relabelAppForm() {
  const form = $("app-form");
  const kind = form.elements.kind.value;
  form.querySelectorAll("[data-job]").forEach((n) => { n.textContent = n.dataset[kind] || n.dataset.job; });
  form.querySelectorAll(".phd-only").forEach((n) => { n.hidden = kind !== "phd"; });
  $("fetch-ad").textContent = kind === "phd" ? "Get the page from this link" : "Get the ad from this link";
}

$("app-form").elements.kind.addEventListener("change", relabelAppForm);
